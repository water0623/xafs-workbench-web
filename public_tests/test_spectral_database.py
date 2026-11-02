from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "v2" / "browser-fit.html").read_text(encoding="utf-8")
JS = (ROOT / "v2" / "static" / "browser-fit.js").read_text(encoding="utf-8")


def test_database_metadata_and_actions_are_visible():
    for control in (
        "db-sample-name",
        "db-formula",
        "db-sample-id",
        "db-experiment-date",
        "db-notes",
        "download-db-record",
        "send-to-chemistry",
    ):
        assert f'id="{control}"' in HTML


def test_hard_xas_record_contains_spectra_fit_and_coordination():
    assert "synchrochem.spectral-record/v1" in JS
    assert "record_type:'hard_xas_exafs'" in JS
    assert "k_space:lastResult.k_space" in JS
    assert "r_space:lastResult.r_space" in JS
    assert "statistics:lastResult.statistics" in JS
    assert "paths:lastResult.paths" in JS
    assert "protocol:lastResult.protocol_audit" in JS


def test_cross_origin_handoff_is_restricted_and_has_json_fallback():
    assert "CHEMISTRY_ORIGIN='https://cocoyou123456789-sketch.github.io'" in JS
    assert "target.postMessage(message,CHEMISTRY_ORIGIN)" in JS
    assert "synchrochem:spectral-ack" in JS
    assert "已自动下载 JSON" in JS
