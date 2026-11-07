(() => {
  if (!new URLSearchParams(window.location.search).has('growth-workbench-smoke')) return;
  const failures=[];
  const check=(condition,message)=>{if(!condition)failures.push(message);};
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const waitFor=async(predicate,timeout=12000)=>{
    const start=performance.now();
    while(performance.now()-start<timeout){
      if(await predicate())return true;
      await sleep(40);
    }
    return false;
  };
  const finish=()=>{
    const marker=document.createElement('div');
    marker.id='growth-workbench-smoke';
    marker.textContent=failures.length?'GROWTH_WORKBENCH_SMOKE_FAIL: '+failures.join(' | ')
      :'GROWTH_WORKBENCH_SMOKE_PASS';
    document.body.appendChild(marker);
  };
  const field=(form,name,value)=>{
    const input=form.elements.namedItem(name);
    if(!input)throw Error('Missing form control '+name);
    if(typeof value==='boolean')input.checked=value;
    else input.value=String(value);
  };
  const submit=async(name,values,accepted)=>{
    const form=document.querySelector('form[data-growth-form="'+name+'"]');
    if(!form)throw Error('Missing growth form '+name);
    for(const [key,value] of Object.entries(values))field(form,key,value);
    form.requestSubmit();
    const done=await waitFor(accepted);
    check(done,'Form did not persist: '+name+' '+growthState.notice);
  };
  window.addEventListener('DOMContentLoaded',()=>{
    setTimeout(()=>void(async()=>{
      const runtime=await waitFor(()=>runtimeAvailability==='ready',16000);
      check(runtime,'API runtime unavailable: '+runtimeAvailability);
      go('growthOps');
      check(await waitFor(()=>growthSnapshot&&document.querySelector('[data-growth-tab="customers"]')),
        'Growth workbench failed to load');
      check(document.querySelectorAll('[data-growth-tab]').length===5,'Missing workbench navigation');
      const suffix=String(Date.now());
      const customer='browser_customer_'+suffix;
      const segment='browser_segment_'+suffix;
      const creative='browser_creative_'+suffix;
      const journey='browser_journey_'+suffix;
      const experiment='browser_experiment_'+suffix;

      await growthOpenTab('customers');
      await submit('customer',{
        new_customer_id:customer,new_customer_key:'lifecycle',new_customer_value:'new',
        new_customer_consent:true
      },()=>growthSnapshot.customers.some(row=>row.customer_id===customer));
      const picker=document.querySelector('#growth-profile_customer_id');
      picker.value=customer;
      picker.dispatchEvent(new Event('change',{bubbles:true}));
      document.querySelector('#growth-open-profile').click();
      check(await waitFor(()=>growthState.profile?.customer.customer_id===customer),
        'Customer profile did not load from database');
      check(growthState.profile?.customer.consent===true,'Customer consent not persisted');

      await submit('segment',{
        new_segment_id:segment,new_segment_name:'Browser segment',
        new_segment_key:'lifecycle',new_segment_value:'new'
      },()=>growthSnapshot.segments.some(row=>row.segment_id===segment));
      document.querySelector('#growth-preview-segment').value=segment;
      document.querySelector('#growth-preview-segment-button').click();
      check(await waitFor(()=>growthState.segmentPreview?.segment_id===segment),
        'Segment preview missing');
      check(growthState.segmentPreview?.customer_ids.includes(customer),'Segment preview lost new customer');

      await growthOpenTab('assets');
      await submit('creative',{
        new_creative_id:creative,new_creative_channel:'email',
        new_creative_title:'Welcome message',new_creative_body:'Hello from browser smoke'
      },()=>growthSnapshot.creatives.some(row=>row.creative_id===creative));

      await growthOpenTab('journeys');
      await submit('journey',{
        new_journey_id:journey,new_journey_name:'Welcome journey',
        new_journey_trigger:'signup',new_journey_segment:segment,
        new_journey_creative:creative,new_journey_offer:'',new_journey_delay:0
      },()=>growthSnapshot.journeys.some(row=>row.journey_id===journey));
      const activate=document.querySelector('[data-growth-journey="'+journey+'"][data-journey-command="activate"]');
      check(Boolean(activate),'Journey activate button missing');
      if(activate)activate.click();
      check(await waitFor(()=>growthSnapshot.journeys.some(row=>row.journey_id===journey&&row.active)),
        'Journey activation not persisted');

      await growthOpenTab('experiments');
      await submit('experiment',{
        new_experiment_id:experiment,new_experiment_name:'Browser checkout experiment',
        new_experiment_metric:'purchase',new_experiment_control:'holdout',
        new_experiment_treatment:'offer',new_experiment_weight:50,
        new_experiment_days:7
      },()=>growthSnapshot.experiments.some(row=>row.experiment_id===experiment));
      await submit('experiment-exposure',{
        exposure_experiment:experiment,exposure_customer:customer,
        exposure_surface:'growth_workspace'
      },()=>growthSnapshot.overview.counts.exposures>0);
      await submit('personalization',{
        personalization_customer:customer,personalization_action:'free_shipping',
        personalization_frequency:1,personalization_budget:100
      },()=>growthState.decision?.customer_id===customer);
      check(growthState.decision?.action_distribution.NO_TREATMENT>0,
        'Decision missing explicit no-treatment probability');
      const expose=document.querySelector('#growth-confirm-exposure');
      check(Boolean(expose),'Personalization exposure confirmation missing');
      if(expose)expose.click();
      check(await waitFor(()=>growthState.decision?.exposure_confirmed===true),
        'Real exposure confirmation did not persist');
      await submit('offline-evidence',{ope_action:'NO_TREATMENT',ope_source:'observed'},
        ()=>growthState.evidence!==null);
      check(growthState.evidence?.promotion_allowed===false,
        'Offline evidence incorrectly allows automatic promotion');
      document.querySelector('#growth-report-id').value=experiment;
      document.querySelector('#growth-get-report').click();
      check(await waitFor(()=>growthState.report?.experiment_id===experiment),
        'Experiment maturation report missing');
      check(growthState.report?.causal_claim===false,'Experiment report claimed causality');

      await growthOpenTab('overview');
      await submit('event',{event_customer:customer,event_name:'signup'},
        ()=>growthSnapshot.events.some(row=>row.customer_id===customer&&row.name==='signup'));
      await growthOpenTab('journeys');
      document.querySelector('#growth-process-due').click();
      check(await waitFor(()=>growthSnapshot.deliveries.some(row=>row.journey_id===journey)),
        'Journey did not reach delivery intent');
      const delivery=growthSnapshot.deliveries.find(row=>row.journey_id===journey);
      check(delivery?.status==='queued','Real delivery unexpectedly sent or simulated');

      go('experiments');
      check(await waitFor(()=>document.querySelector('#view')?.textContent.includes('数据库实验反馈')),
        'Main experiment center not connected to PostgreSQL result cards');

      const stored=await api('/api/growth/customers/'+encodeURIComponent(customer));
      check(stored.customer.customer_id===customer,'Browser mutations missing on backend');
      const deliveries=await api('/api/growth/deliveries');
      check(deliveries.filter(row=>row.journey_id===journey).length===1,
        'Journey intent duplicated after browser operations');
      finish();
    })().catch(error=>{failures.push(error?.message||String(error));finish();}),0);
  });
})();
