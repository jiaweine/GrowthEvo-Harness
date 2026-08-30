from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_citation_metadata_describes_current_research_software_without_fake_release() -> None:
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert "cff-version: 1.2.0" in citation
    assert 'title: "GrowthEvo-Harness"' in citation
    assert "type: software" in citation
    assert '- name: "GrowthEvo contributors"' in citation
    assert 'repository-code: "https://github.com/jiaweine/GrowthEvo-Harness"' in citation
    assert "off-policy evaluation" in citation
    assert "safe policy improvement" in citation

    top_level_keys = {
        line.split(":", 1)[0]
        for line in citation.splitlines()
        if line and not line.startswith((" ", "-")) and ":" in line
    }
    assert "doi" not in top_level_keys
    assert "date-released" not in top_level_keys
    assert "version" not in top_level_keys
