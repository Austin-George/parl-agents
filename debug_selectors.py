# import asyncio
# from playwright.async_api import async_playwright

# async def debug():
#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=False)
#         page = await browser.new_page()
#         await page.goto("http://localhost:3000")
#         await page.wait_for_load_state("networkidle")
#         await page.wait_for_timeout(2000)

#         # Click some buttons first so display has a value
#         await page.locator('button:has-text("2")').first.click()
#         await page.wait_for_timeout(300)
#         await page.locator('button:has-text("+")').first.click()
#         await page.wait_for_timeout(300)
#         await page.locator('button:has-text("3")').first.click()
#         await page.wait_for_timeout(300)
#         await page.locator('button:has-text("=")').first.click()
#         await page.wait_for_timeout(500)

#         # Dump the FULL page HTML so we can see exact class names
#         html = await page.content()
        
#         # Print just the body part to keep it readable
#         # We're looking for the display element's actual class name
#         start = html.find('<body')
#         print("PAGE HTML:")
#         print(html[start:start+3000])
#         print("\n" + "="*50)

#         # Also try to find ALL elements with their text
#         all_elements = await page.locator('*').all()
#         print(f"\nTotal elements on page: {len(all_elements)}")

#         # Get all divs with text content
#         print("\nDivs with text content:")
#         divs = await page.locator('div').all()
#         for div in divs[:30]:
#             try:
#                 text = await div.inner_text()
#                 classname = await div.get_attribute('class')
#                 if text.strip() and len(text.strip()) < 50:
#                     print(f"  class='{classname}' text='{text.strip()}'")
#             except:
#                 pass

#         await browser.close()

# asyncio.run(debug())