from pathlib import Path


ROD_BROWSER_PATHS = tuple(
    sorted(
        (Path.home() / ".cache" / "rod" / "browser").glob("chromium-*/Chromium.app/Contents/MacOS/Chromium"),
        reverse=True,
    )
)

SYSTEM_BROWSER_PATHS = ROD_BROWSER_PATHS + (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path("/usr/bin/google-chrome"),
)


def system_chromium_path() -> Path | None:
    return next((path for path in SYSTEM_BROWSER_PATHS if path.is_file()), None)


async def launch_chromium(playwright):
    try:
        return await playwright.chromium.launch(headless=True)
    except Exception as original_error:
        for path in SYSTEM_BROWSER_PATHS:
            if path.is_file():
                try:
                    return await playwright.chromium.launch(headless=True, executable_path=str(path))
                except Exception:
                    continue
        raise original_error
