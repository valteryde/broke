from playwright.sync_api import Page, expect
import re

def login(page: Page, base_url: str):
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", "user")
    page.fill("input[name='password']", "code")
    page.click("button[type='submit']")

def test_homepage_redirects_to_login(page: Page, run_server):
    # Without login, it should redirect
    page.goto(run_server)
    expect(page).to_have_url(f"{run_server}/login?next=/news")

def test_tickets_page_loads_with_login(page: Page, run_server):
    login(page, run_server)
    
    # After login, we might be redirected to /news (default home) or whatever the logic is.
    # Let's explicitly go to tickets now.
    page.goto(f"{run_server}/tickets")
    
    # Match /tickets with optional query params
    expect(page).to_have_url(re.compile(r".*/tickets.*"))
    expect(page).to_have_title("Tickets | Broke")
