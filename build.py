"""exe 빌드: python build.py [--test]
--test : 관리자 권한 요구 없이 build/test 에 빌드 (자동 검증용)
기본   : 관리자 권한 manifest 포함, dist/DopamineDetox.exe → 바탕화면에 복사
"""
import os
import shutil
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
test = "--test" in sys.argv
name = "DopamineDetox_test" if test else "DopamineDetox"
dist = os.path.join(ROOT, "build", "testdist") if test else os.path.join(ROOT, "dist")

args = [
    os.path.join(ROOT, "app.py"),
    "--name", name,
    "--onefile", "--noconsole", "--noconfirm", "--clean",
    "--distpath", dist,
    "--workpath", os.path.join(ROOT, "build", "work-" + name),
    "--specpath", os.path.join(ROOT, "build"),
    "--icon", os.path.join(ROOT, "assets", "icon.ico"),
    "--add-data", f"{os.path.join(ROOT, 'ui')}{os.pathsep}ui",
    "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",
    "--collect-all", "uiautomation",
    "--hidden-import", "comtypes.stream",
    "--hidden-import", "pystray._win32",
]
if not test:
    args.append("--uac-admin")
PyInstaller.__main__.run(args)

exe = os.path.join(dist, name + ".exe")
if not test:
    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    target = os.path.join(desktop, name + ".exe")
    try:
        shutil.copy2(exe, target)
    except PermissionError:
        # 앱이 실행 중이면 덮어쓸 수 없다 → 실행 중인 파일을 옮기고(같은 드라이브면 허용됨) 새 파일을 놓는다
        import time
        old = os.path.join(ROOT, "build", f"{name}.running-{int(time.time())}.exe")
        os.replace(target, old)
        shutil.copy2(exe, target)
        print("running exe moved to", old, "- restart the app to use the new version")
    print("copied to", os.path.join(desktop, name + ".exe"))
print("built", exe)
