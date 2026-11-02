"""tools/btbn_stages.py：照 BtbN 的 generate.sh 算出 win64、lgpl、9.0 這個 build 建了哪些函式庫（#274）。

用自己寫的小 scripts.d 測解析的規則；真的 BtbN 腳本由 python -m tools.third_party_licenses 產生清單時
解析，並以 THIRD_PARTY_NOTICES.txt 記的 configure 參數交叉檢查。
"""
import pytest

from tools import btbn_stages
from tools.btbn_stages import GitSource, Scripts, SvnSource


def script(*, repo="https://example.com/x.git", commit="c" * 40, enabled="return 0", depends=None,
           dl=None, configure=None, extra="") -> str:
    parts = [f'SCRIPT_REPO="{repo}"', f'SCRIPT_COMMIT="{commit}"', extra,
             f"ffbuild_enabled() {{\n    {enabled}\n}}"]
    if depends is not None:
        parts.append("ffbuild_depends() {\n" + "".join(f"    echo {d}\n" for d in depends) + "}")
    if dl is not None:
        parts.append("ffbuild_dockerdl() {\n" + "".join(f"    {line}\n" for line in dl) + "}")
    if configure is not None:
        parts.append(f"ffbuild_configure() {{\n    echo {configure}\n}}")
    return "#!/bin/bash\n\n" + "\n\n".join(parts) + "\n"


def tree(**stages: str) -> dict[str, str]:
    """{"50_aom": 內容} → {"scripts.d/50-aom.sh": 內容}；名稱裡的 __ 是資料夾。"""
    files = {"scripts.d/15-base.sh": 'SCRIPT_SKIP="1"\n\nffbuild_depends() {\n    return 0\n}\n'}
    for key, text in stages.items():
        path = "/".join(part.replace("_", "-", 1) for part in key.split("__"))
        files[f"scripts.d/{path}.sh"] = text
    return files


def final(*names: str) -> str:
    return 'SCRIPT_SKIP="1"\n\nffbuild_depends() {\n' + "".join(f"    echo {n}\n" for n in names) + "}\n"


class TestEnabled:
    @pytest.mark.parametrize(("body", "expected"), [
        ("return 0", True),
        ("return -1", False),
        ("[[ $TARGET == win* ]] || return -1\n    return 0", True),
        ("[[ $TARGET != linux* ]] && return -1\n    return 0", False),
        ("[[ $VARIANT == lgpl* ]] && return -1\n    return 0", False),
        ("[[ $VARIANT == nonfree* ]] || return -1\n    return 0", False),
        ("(( $(ffbuild_ffver) >= 900 )) || return -1\n    return 0", True),
        ("(( $(ffbuild_ffver) <= 900 )) && return -1\n    return 0", False),
        ("(( $(ffbuild_ffver) > 900 )) || return -1\n    return 0", False),
        ("[[ $TARGET == win* && $ADDINS_STR == *9.0* ]] && return -1\n    return 0", False),
        ("[[ $TARGET == winarm64 ]] && (( $(ffbuild_ffver) <= 801 )) && return -1\n    return 0", True),
        ("[[ $TARGET == win* ]]", True),
        ("[[ $TARGET == linux* ]]", False),
    ])
    def test_conditions(self, body, expected):
        scripts = Scripts(tree(**{"50_x": script(enabled=body)}))

        assert scripts.enabled(scripts.files["scripts.d/50-x.sh"]) is expected

    def test_subshell_sources_another_script(self):
        scripts = Scripts(tree(**{
            "50_rav1e": script(enabled="[[ $TARGET == win32 ]] && return -1\n    return 0"),
            "55_dedup": script(enabled="( source scripts.d/50-rav1e.sh && ffbuild_enabled ) || return -1\n    return 0"),
        }))

        assert scripts.enabled(scripts.files["scripts.d/55-dedup.sh"]) is True

    def test_unknown_condition_stops(self):
        scripts = Scripts(tree(**{"50_x": script(enabled='[[ -n "$FOO" ]] || return -1')}))

        with pytest.raises(ValueError, match="看不懂的條件"):
            scripts.enabled(scripts.files["scripts.d/50-x.sh"])


class TestStages:
    def test_follows_dependencies_from_the_last_stage(self):
        scripts = Scripts(tree(
            **{"20_zlib": script(repo="https://example.com/zlib.git"),
               "25_png": script(repo="https://example.com/png.git", depends=["base", "zlib"]),
               "50_unused": script(repo="https://example.com/unused.git"),
               "zz_final": final("png")}))

        assert [s.name for s in scripts.stages()] == ["zlib", "png"]

    def test_disabled_stage_and_its_dependencies_are_not_built(self):
        scripts = Scripts(tree(
            **{"20_ssl": script(),
               "50_x264": script(enabled="[[ $VARIANT == lgpl* ]] && return -1\n    return 0",
                                 depends=["base", "ssl"]),
               "zz_final": final("x264")}))

        assert scripts.stages() == []

    def test_folder_stage_needs_its_last_script(self):
        # 資料夾 stage：最後一個腳本成立才建；裡面每個腳本再各自看 ffbuild_enabled
        scripts = Scripts(tree(
            **{"50_curl__40_psl": script(repo="https://example.com/psl.git"),
               "50_curl__50_curl": script(enabled="(( $(ffbuild_ffver) <= 900 )) && return -1\n    return 0"),
               "47_vulkan__40_headers": script(repo="https://example.com/headers.git"),
               "47_vulkan__50_linux_only": script(enabled="[[ $TARGET != linux* ]] && return -1\n    return 0"),
               "47_vulkan__99_enable": 'SCRIPT_SKIP="1"\n',
               "zz_final": final("curl", "vulkan")}))

        assert [s.script.path for s in scripts.stages()] == ["scripts.d/47-vulkan/40-headers.sh"]

    def test_sources_and_download_steps(self):
        scripts = Scripts(tree(**{
            "20_iconv": script(repo="https://savannah/libiconv.git", extra=(
                'SCRIPT_MIRROR="git://mirror/libiconv.git"\n'
                'SCRIPT_REPO2="https://savannah/gnulib.git"\nSCRIPT_MIRROR2="https://github.com/gnulib.git"\n'
                f'SCRIPT_COMMIT2="{"d" * 40}"')),
            "50_jxl": script(dl=["default_dl .", 'echo "git submodule update --init --recursive --depth 1 '
                                 '--recommend-shallow third_party/highway"']),
            "50_glib": script(dl=["default_dl .", 'echo "git submodule update --init --recursive --depth=1"',
                                  'echo "meson subprojects download proxy-libintl"']),
            "50_shaderc": script(dl=["default_dl .", 'echo "./utils/git-sync-deps || exit $?"']),
            "50_amf": script(dl=["default_dl .", 'echo "rm -rf .git Thirdparty"']),
            "50_rav1e": script(extra="ffbuild_dockerbuild() {\n    cargo cinstall\n}"),
            "50_lame": 'SCRIPT_REPO="https://svn.example/p/lame/svn/trunk/lame"\nSCRIPT_REV="6835"\n',
            "zz_final": final("iconv", "jxl", "glib", "shaderc", "amf", "rav1e", "lame"),
        }))

        stages = {s.name: s for s in scripts.stages()}

        assert stages["iconv"].sources == [
            GitSource("https://savannah/libiconv.git", "c" * 40, ("git://mirror/libiconv.git",)),
            GitSource("https://savannah/gnulib.git", "d" * 40, ("https://github.com/gnulib.git",))]
        assert stages["iconv"].submodules is None
        assert stages["jxl"].submodules == ("third_party/highway",)
        assert stages["glib"].submodules == ()
        assert stages["glib"].meson_wraps == ("proxy-libintl",)
        assert stages["shaderc"].git_sync_deps
        assert stages["amf"].removed == ("Thirdparty",)
        assert stages["rav1e"].cargo and not stages["glib"].cargo
        assert stages["lame"].sources == [SvnSource("https://svn.example/p/lame/svn/trunk/lame", "6835")]

    def test_unknown_download_step_stops(self):
        scripts = Scripts(tree(**{"50_x": script(dl=['echo "curl https://example.com/x.tar.gz | tar x"']),
                                  "zz_final": final("x")}))

        with pytest.raises(ValueError, match="下載步驟有看不懂的一行"):
            scripts.stages()

    def test_unknown_dependency_line_stops(self):
        scripts = Scripts(tree(**{"50_x": script(depends=["base"]).replace("echo base", 'echo "$DEP"'),
                                  "zz_final": final("x")}))

        with pytest.raises(ValueError, match="ffbuild_depends 有看不懂的一行"):
            scripts.stages()

    def test_missing_stage_stops(self):
        with pytest.raises(ValueError, match="找不到 stage「nope」"):
            Scripts(tree(zz_final=final("nope"))).stages()

    def test_configure_flags(self):
        scripts = Scripts(tree(**{"50_ffnv": script(configure="--enable-ffnvcodec --enable-cuda-llvm")}))

        assert scripts.configure_flags(scripts.files["scripts.d/50-ffnv.sh"]) == {
            "--enable-ffnvcodec", "--enable-cuda-llvm"}


def test_build_is_win64_lgpl_9_0():
    # 和 build_release.ps1 的 $FfmpegAsset（…-win64-lgpl-9.0.zip）一致
    assert (btbn_stages.TARGET, btbn_stages.VARIANT, btbn_stages.ADDINS_STR) == ("win64", "lgpl", "9.0")
