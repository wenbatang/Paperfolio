import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as pdf

from app import App
from cloud_translate import KEYS, cloud_text
from library import Library
from translation_window import TranslationWindow


def sample_pdf(path, text):
    with pdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        doc.save(path)


class LibraryWorkflows(unittest.TestCase):
    def test_storage_changes_and_duplicate_repair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lib = Library(root / "db")
            try:
                src = root / "one.pdf"
                sample_pdf(src, "first paper")
                first, _ = lib.import_pdf(src)
                old = lib.original_record(first)
                lib.save_preferences({"storage": str(root / "external")})
                other = root / "two.pdf"
                sample_pdf(other, "second paper")
                second, _ = lib.import_pdf(other)
                self.assertTrue(lib.has_file(old))
                original = lib.original_record(second)
                self.assertTrue(Path(original["path"]).is_relative_to(root / "external"))
                lib.save_note(original["id"], 1, "note")
                (lib.root / old["path"]).unlink()
                self.assertEqual(lib.import_pdf(src), (first, False))
                self.assertTrue(lib.has_file(old))
                outputs = root / "results"
                outputs.mkdir()
                for name in ("mono", "dual"):
                    sample_pdf(outputs / f"paper-{name}.pdf", name)
                lib.publish(second, outputs, "test")
                self.assertEqual(len(lib.files(second)), 3)
                self.assertTrue(all(Path(f["path"]).is_relative_to(root / "external") for f in lib.files(second)))
            finally:
                lib.db.close()
            lib = Library(root / "db")
            try:
                self.assertEqual(lib.storage, root / "external")
                self.assertEqual(lib.notes(second)[0]["body"], "note")
            finally:
                lib.db.close()

    def test_tab_survives_paper_and_multiselection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = App(root / "db")
            app.withdraw()
            try:
                for index in (1, 2):
                    path = root / f"{index}.pdf"
                    sample_pdf(path, str(index))
                    app.library.import_pdf(path)
                app.refresh(1)
                for tab in (1, 2):
                    app.detail_tabs.select(tab)
                    app.refresh(2)
                    self.assertEqual(app.detail_tabs.index("current"), tab)
                    app.refresh((1, 2))
                    app.refresh(1)
                    self.assertEqual(app.detail_tabs.index("current"), tab)
                app.library.save_preferences({"theme": "雾蓝", "provider": "google"})
                app.apply_theme()
                self.assertEqual(app.paper_color, "#e5edf4")
                with patch("translation_window.installed_models") as detect:
                    win = TranslationWindow(app, app.rows[1])
                    self.assertEqual(win.service_id(), "google")
                    self.assertTrue(win.key_entry.grid_info())
                    self.assertFalse(win.config_entry.master.grid_info())
                    detect.assert_not_called()
                    win.destroy()
            finally:
                app.close()


class CloudTranslation(unittest.TestCase):
    def test_paragraph_worker_writes_both_editions_without_ollama(self):
        import translate
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            sample_pdf(source, "A physical model of liquid water.")
            for provider in KEYS:
                dest = root / provider
                argv = ["translate", str(source), str(dest), "--mode", "paragraph", "--provider", provider]
                with self.subTest(provider=provider), patch.object(sys, "argv", argv), \
                     patch("translate.installed_models", side_effect=AssertionError("unexpected Ollama request")), \
                     patch("translate.cloud_text", return_value="液态水的物理模型。") as service:
                    translate.main()
                    self.assertEqual(service.call_args.args[:3], (provider, "en", "zh-CN"))
                    for kind in ("mono", "dual"):
                        with pdf.open(dest / f"paper-{kind}.pdf") as output:
                            self.assertGreaterEqual(len(output), 1)

    def test_both_official_endpoints_and_placeholders(self):
        source = "Use <b1>water</b1> and {v2}."
        for provider, key in KEYS.items():
            def respond(req, timeout):
                self.assertEqual(timeout, 45)
                request = json.loads(req.data)
                if provider == "microsoft":
                    self.assertIn("to=zh-Hans", req.full_url)
                    self.assertEqual(req.get_header("Ocp-apim-subscription-region"), "eastasia")
                    text = request[0]["Text"]
                    response = [{"translations": [{"text": text.replace("water", "水")}]}]
                else:
                    self.assertEqual(request["target"], "zh-CN")
                    self.assertEqual(req.get_header("X-goog-api-key"), "test-value")
                    text = request["q"]
                    response = {"data": {"translations": [{"translatedText": text.replace("water", "水")}]}}
                self.assertIn('class="notranslate"', text)
                self.assertNotIn("test-value", req.full_url)
                return io.BytesIO(json.dumps(response).encode())
            with self.subTest(provider=provider), patch.dict(os.environ, {key: "test-value", "AZURE_TRANSLATOR_REGION": "eastasia"}):
                with patch("cloud_translate.urlopen", side_effect=respond):
                    self.assertEqual(cloud_text(provider, "en", "zh-CN", source), source.replace("water", "水"))
