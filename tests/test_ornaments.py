from pathlib import Path
import tempfile
import unittest

from app import App
from ornaments import DENSITIES, STYLES, MotifStrip, glyph, preference
from library import Library


class OrnamentTests(unittest.TestCase):
    def test_styles_have_distinct_glyphs(self):
        images = set()
        for style, palette in STYLES.items():
            for motif in palette.motifs:
                image = glyph(style, motif, 32)
                self.assertTrue(image.getbbox())
                images.add(image.tobytes())
        self.assertEqual(len(images), 36)

    def test_ornaments_preserve_table_viewport_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            app = App(folder)
            try:
                for i in range(40):
                    app.library.db.execute(
                        "INSERT INTO papers(digest,title,added) VALUES(?,?,?)",
                        (str(i), f"Paper {i:02}", str(i)),
                    )
                app.library.db.commit()
                app.refresh((10, 11))
                for geometry in ("950x610", "1220x760"):
                    app.geometry(geometry)
                    app.update()
                    app.table.see("11")
                    app.update()

                    def measurements():
                        t = app.table
                        return (
                            t.winfo_rootx(),
                            t.winfo_rooty(),
                            t.winfo_width(),
                            t.winfo_height(),
                            t.bbox("11"),
                            t.yview(),
                            app.selection(),
                        )

                    expected = measurements()
                    for style in STYLES:
                        for density in DENSITIES:
                            app.library.save_preferences(
                                {"ornament_style": style, "ornament_density": density}
                            )
                            app.apply_theme()
                            app.update()
                            self.assertEqual(measurements(), expected)
                self.assertFalse(any(isinstance(w, MotifStrip) for w in app.table_zone.winfo_children()))
                self.assertFalse(app.table.winfo_children())
                for i in range(50):
                    app.library.db.execute("INSERT INTO collections(name) VALUES(?)", (str(i),))
                app.library.db.commit()
                app.library.save_preferences({"ornament_density": "丰富"})
                app.apply_theme()
                app.reload_collections()
                app.update()
                self.assertFalse(app.side_motifs.winfo_ismapped())
                self.assertEqual(app.collections.size(), 50)
            finally:
                app.close()
            lib = Library(Path(folder))
            try:
                self.assertEqual(preference(lib), "night")
            finally:
                lib.db.close()
