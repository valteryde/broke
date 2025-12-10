from playwright.sync_api import Page, expect
import re
import time

def login(page: Page, base_url: str):
    page.goto(f"{base_url}/login")
    page.fill("input[name='username']", "user")
    page.fill("input[name='password']", "code")
    page.click("button[type='submit']")

def test_ticket_lifecycle(page: Page, run_server):
    # 1. Login
    login(page, run_server)
    
    # 2. Go to Tickets list
    page.goto(f"{run_server}/tickets")
    
    # 3. Create Ticket
    # Click "Add" button
    page.click(".list-create-btn")
    
    # Wait for modal and select first project
    page.wait_for_selector(".modal-project-item")
    page.click(".modal-project-item >> nth=0")
    
    # Click Create
    page.click("#create-ticket-btn")
    
    # Wait for redirection to ticket detail
    # URL pattern: /tickets/PROJECT-ID/TICKET-ID (e.g. /tickets/BAC/BAC-123)
    page.wait_for_url(re.compile(r".*/tickets/[A-Z]+/[A-Z0-9-]+"))
    
    # 4. Edit Ticket Title
    new_title = f"Test Ticket {int(time.time())}"
    # Fill and blur to trigger save
    page.fill(".ticket-title", new_title)
    page.locator(".ticket-title").blur()
    
    # Reload page to verify persistence
    page.reload()
    expect(page.locator(".ticket-title")).to_have_value(new_title)
    
    # 5. Edit Description (Quill)
    description_text = "This is an automated test description."
    # Quill editor content is inside .ql-editor
    page.locator("#ticket-description-editor .ql-editor").fill(description_text)
    
    # Wait for save (checking indicator or arbitrary wait? editor.js debounces save)
    # editor.js shows .ticket-save-indicator when saving
    # Let's wait a bit to be safe as the indicator might be fleeting
    page.wait_for_timeout(1000) 
    
    # Reload to verify
    page.reload()
    # Quill renders HTML, so we check text content
    expect(page.locator("#ticket-description-editor .ql-editor")).to_contain_text(description_text)
    
    # 6. Change Status
    # Click status dropdown
    page.click('[data-property="status"]')
    # Click a different status (e.g., "In Progress" or "in-progress")
    # We explicitly look for a dropdown item. 
    # Based on editor.js: items are rendered by Dropdown class.
    # Usually they are .dropdown-item. Let's try to click one that is NOT the current one.
    # Assuming "todo" is default, let's click "in-progress" if available.
    # Or just click the second item in the dropdown.
    page.click(".dropdown-menu .dropdown-item >> nth=1")
    
    page.wait_for_timeout(500) # Wait for save
    
    # 7. Add Comment
    comment_text = "Automated comment."
    page.locator("#ticket-comment-editor .ql-editor").fill(comment_text)
    page.click("#submit-comment")
    
    # Verify comment appears in activity list
    expect(page.locator(".ticket-activity-list")).to_contain_text(comment_text)
    
    # Reload and verify comment persists
    page.reload()
    expect(page.locator(".ticket-activity-list")).to_contain_text(comment_text)
