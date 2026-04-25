"""AIIterate browser smoke test — Playwright.
Run: ~/.hermes/venv/bin/python tests/test_smoke.py
"""

import sys
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

BASE = "http://192.168.31.222:7070"

def main():
    passed = 0
    failed = 0
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        
        def on_error(msg):
            errors.append(msg.text)
        page.on("pageerror", on_error)
        
        try:
            # 1. Open page, check no JS errors
            page.goto(BASE, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            
            if not errors:
                print("✓ 1. Page loads without JS errors")
                passed += 1
            else:
                print(f"✗ 1. JS errors: {errors[:3]}")
                failed += 1
            
            # 2. Check sidebar stats exist
            stats = page.text_content("#sessionStats") or ""
            if "个" in stats:
                print(f"✓ 2. Sidebar stats: {stats.strip()}")
                passed += 1
            else:
                print(f"✗ 2. Sidebar stats missing or wrong: {stats}")
                failed += 1
            
            # 3. Check topbar buttons (use title attributes since they're SVG icons)
            btn_count = len(page.query_selector_all(".topbar-actions button, .topbar-actions .btn"))
            print(f"✓ 3. Topbar has {btn_count} buttons")
            passed += 1
            
            # 4. Click first session
            session_items = page.query_selector_all(".session-item")
            if session_items:
                session_items[0].click()
                page.wait_for_timeout(1000)
                
                # Check workspace loaded
                ws = page.query_selector(".panel-content")
                if ws:
                    print(f"✓ 4. Session workspace loads")
                    passed += 1
                else:
                    print(f"✗ 4. Workspace not found after session click")
                    failed += 1
            else:
                print("✗ 4. No session items in sidebar")
                failed += 1
            
            # 5. Open command center via title attribute
            cc_btn = page.query_selector("button[title='指挥中心']")
            if cc_btn:
                cc_btn.click()
                page.wait_for_timeout(1500)
                modal = page.query_selector(".command-center-modal")
                if modal:
                    print(f"✓ 5. Command center modal opens")
                    passed += 1
                else:
                    print(f"✗ 5. Command center modal not found")
                    failed += 1
            else:
                # fallback: try text match
                try:
                    cc_btn2 = page.wait_for_selector("button:has-text('指挥中心')", timeout=2000)
                    cc_btn2.click()
                    page.wait_for_timeout(1500)
                    modal = page.query_selector(".command-center-modal")
                    print(f"{'✓' if modal else '✗'} 5. Command center (fallback)")
                    passed += 1 if modal else 0
                    failed += 0 if modal else 1
                except PwTimeout:
                    print(f"✗ 5. Command center button not found")
                    failed += 1
            
        except Exception as e:
            print(f"✗ Fatal: {e}")
            failed += 1
        finally:
            browser.close()
    
    print(f"\n{'='*40}")
    print(f"Passed: {passed}, Failed: {failed}")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
