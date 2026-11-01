from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "v2" / "browser-fit.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "v2" / "static" / "browser-fit.js").read_text(encoding="utf-8")


class HardXasLiteratureTests(unittest.TestCase):
    def test_literature_constrained_controls_are_published(self):
        for token in (
            'id="analysis-role"',
            'id="stage-mode"',
            'id="multi-start-count"',
            'name="audit_kweight"',
            'id="protocol-audit"',
            'id="stability"',
            'id="wavelet-residual"',
            'id="download-method-report"',
            "PMC2816928",
        ):
            self.assertIn(token, PAGE)

    def test_engine_enforces_identifiability_and_reproducibility(self):
        for token in (
            "function applyAmplitudePolicy",
            "function degreesOfFreedomGuard",
            "if(nvar>=nind)throw new Error",
            "function mulberry32",
            "deterministic candidate-screened multi-start",
            "kweights_audited",
            "paper2agent_review_status:'reviewed_with_limitations'",
        ):
            self.assertIn(token, SCRIPT)
        self.assertNotIn("eval(", SCRIPT)
        self.assertNotIn("new Function(", SCRIPT)

    def test_reviewed_paper2agent_package_is_deployed_with_v2(self):
        method_root = ROOT / "v2" / "methods" / "hard-xas-methods"
        skill = (method_root / "SKILL.md").read_text(encoding="utf-8")
        paper = (method_root / "references" / "paper.md").read_text(encoding="utf-8")
        supplement = (method_root / "references" / "supplement.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: hard-xas-methods", skill)
        self.assertIn("reviewed_with_limitations", SCRIPT)
        self.assertIn("10.1107/S090904950904655X", paper)
        self.assertIn("Nind", supplement)


if __name__ == "__main__":
    unittest.main()
