import runpy

from hiyoko_viewer.config import constants


def test_generate_reg_entries_outputs_file_associations_and_classes(capsys) -> None:
    runpy.run_module("generate_reg_entries", run_name="__main__")

    output = capsys.readouterr().out

    assert "Capabilities\\FileAssociations" in output
    assert "セクション3 (AssocFile 定義)" in output
    for ext in constants.SUPPORTED_EXTENSIONS:
        ext_upper = ext.replace(".", "").upper()
        assert f'"{ext}"="HiyokoViewer.AssocFile.{ext_upper}"' in output
        assert (
            f"[HKEY_CURRENT_USER\\Software\\Classes\\HiyokoViewer.AssocFile.{ext_upper}]" in output
        )
        assert f'@="{ext_upper} Image File"' in output
