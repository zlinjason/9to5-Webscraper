"""
9to5Google Article Reader - Personal Queue System
Fetches articles from WordPress API, maintains an inbox, and allows batch marking as read.

===========================================
COMMANDS (run from terminal):
===========================================
python reader.py fetch   - Get new articles since last clear
python reader.py review  - Display inbox (oldest at bottom, newest at top)
python reader.py clear   - Delete ALL articles AND update timestamp (mass mark as read)
===========================================

The timestamp only updates when you run 'clear', so you never miss articles
even if your computer is off for days.
"""

import json
import requests
from datetime import datetime, timezone
from pathlib import Path
import time
import argparse

# ============================================================================
# CONFIGURATION
# ============================================================================

INBOX_FILE = "inbox.json"      # Stores unread articles
STATE_FILE = "state.json"       # Stores last fetch time (but NOT updated until clear)
API_URL = "https://9to5google.com/wp-json/wp/v2/posts"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PersonalReader/1.0"

# ============================================================================
# FILE HANDLING FUNCTIONS
# ============================================================================

def load_json(path):
    """Load JSON from file. Returns empty list/dict if file doesn't exist."""
    if not Path(path).exists():
        # Return appropriate empty structure based on filename
        return [] if "inbox" in str(path) else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    """Save data to JSON file with pretty formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ============================================================================
# API FETCHING FUNCTIONS
# ============================================================================

def fetch_articles_page(page=1, per_page=100):
    """
    Fetch one page of articles from the WordPress API.
    
    Args:
        page: Page number (1, 2, 3...)
        per_page: Number of articles per page (max 100)
    
    Returns:
        List of articles or None if error
    """
    headers = {"User-Agent": USER_AGENT}
    params = {
        "page": page,
        "per_page": per_page,
        "_fields": "id,title,link,date",  # Only fetch what we need (no excerpt)
        "orderby": "date",
        "order": "desc"  # Newest first
    }
    
    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 400:
            return []  # Page doesn't exist
        else:
            print(f"⚠️ API error: {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        print(f"⚠️ Timeout on page {page}")
        return None
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return None

# ============================================================================
# CORE LOGIC: FETCH NEW ARTICLES
# ============================================================================

def fetch_all_new():
    """
    Fetch all articles published since last fetch.
    Keeps paginating through WordPress API until hitting articles older than last_fetched.
    
    IMPORTANT: This function does NOT update last_fetched. That only happens on 'clear'.
    """
    # Load state and inbox
    state = load_json(STATE_FILE)
    # Default to a very old date if this is first run (has timezone info)
    last_fetched_str = state.get("last_fetched", "2026-05-21T00:00:00+00:00")
    last_fetched = datetime.fromisoformat(last_fetched_str)
    
    inbox = load_json(INBOX_FILE)
    existing_urls = {item["url"] for item in inbox}
    
    all_new_items = []
    page = 1
    gap_filled = False
    
    print(f"🔍 Fetching articles since {last_fetched.strftime('%Y-%m-%d %H:%M')}")
    
    # Keep fetching pages until we find articles older than last_fetched
    while not gap_filled:
        print(f"   📄 Page {page}...", end=" ")
        articles = fetch_articles_page(page)
        
        if not articles:
            print("No more pages")
            break
        
        print(f"got {len(articles)} articles")
        
        page_new_items = []
        should_continue = True
        
        # Process each article on this page
        for article in articles:
            # Parse the publication date and ensure it has timezone info (UTC)
            pub_date = datetime.fromisoformat(
                article['date'].replace('Z', '+00:00')
            ).replace(tzinfo=timezone.utc)
            
            # If this article is older than our last fetch, we've caught up
            if pub_date <= last_fetched:
                gap_filled = True
                should_continue = False
                break
            
            # Skip if we already have this URL in inbox
            if article['link'] in existing_urls:
                continue
            
            # This is a new article - add it to our batch
            page_new_items.append({
                "url": article['link'],
                "title": article['title']['rendered'],
                "published": pub_date.isoformat(),
                "fetched": datetime.now(timezone.utc).isoformat()
            })
        
        if page_new_items:
            print(f"      ✨ Found {len(page_new_items)} new articles")
            all_new_items.extend(page_new_items)
            existing_urls.update([item["url"] for item in page_new_items])
        
        if not should_continue:
            break
        
        page += 1
        time.sleep(0.5)  # Be nice to the server
    
    # Add all new articles to inbox (oldest first, so they appear at bottom when reviewing)
    if all_new_items:
        # Sort by published date (oldest first = smallest index when reviewing)
        all_new_items.sort(key=lambda x: x['published'])
        inbox.extend(all_new_items)
        save_json(INBOX_FILE, inbox)
        
        # IMPORTANT: Do NOT update last_fetched here. That only happens on 'clear'.
        
        print(f"\n✅ Added {len(all_new_items)} new articles to inbox")
        print(f"📊 Inbox now has {len(inbox)} unread articles")
        print(f"💡 Run 'review' to see them (oldest at bottom, newest at top)")
    else:
        print(f"\n📭 No new articles found")
    
    return len(all_new_items)

# ============================================================================
# REVIEW FUNCTION: DISPLAY INBOX WITH OLDEST AT BOTTOM
# ============================================================================

def review():
    """
    Display all unread articles (titles and dates only, no summaries).
    NEWEST article is at the TOP with the HIGHEST number.
    OLDEST article is at the BOTTOM with #1.
    This lets you scroll from bottom to top to read oldest to newest.
    """
    inbox = load_json(INBOX_FILE)
    if not inbox:
        print("📭 Inbox empty. Run 'fetch' first.")
        return
    
    # inbox is already sorted oldest first (from fetch_all_new)
    # Display them from newest to oldest (top to bottom)
    # Numbering: newest = highest number, oldest = 1
    reversed_inbox = list(reversed(inbox))
    total = len(inbox)
    
    print(f"\n📰 INBOX ({total} unread articles)")
    print("   (NEWEST at TOP with highest number, OLDEST at BOTTOM as #1)")
    print("=" * 90)
    
    # Display from newest to oldest (top to bottom)
    # display_num starts at total (newest) and counts DOWN to 1 (oldest)
    for idx, item in enumerate(reversed_inbox):
        # Number: total - idx (newest = total, oldest = 1)
        article_num = total - idx
        print(f"\n[{article_num}] {item['title']}")
        print(f"    📅 {item['published'][:10]} | 🔗 {item['url']}")
        print("-" * 90)
    
    print(f"\n💡 Tip: Article #1 (oldest) is at the BOTTOM of this list")
    print(f"💡 Article #{total} (newest) is at the TOP")
    print(f"💡 Run 'clear' to mark ALL as read and update the last-fetched timestamp")

# ============================================================================
# CLEAR FUNCTION: MASS MARK AS READ
# ============================================================================

def clear_inbox():
    """
    Permanently delete all articles in inbox AND update last_fetched timestamp.
    
    This is the ONLY time last_fetched gets updated. This ensures you never miss
    articles between computer shutdowns - the script always knows where it left off.
    """
    inbox = load_json(INBOX_FILE)
    if not inbox:
        print("📭 Inbox already empty")
        return
    
    count = len(inbox)
    print(f"\n⚠️ You are about to PERMANENTLY DELETE {count} articles")
    confirm = input(f"Type 'DELETE {count}' to confirm: ")
    
    if confirm == f"DELETE {count}":
        # Clear the inbox
        save_json(INBOX_FILE, [])
        
        # IMPORTANT: Update last_fetched to NOW so next fetch only gets newer articles
        state = load_json(STATE_FILE)
        state["last_fetched"] = datetime.now(timezone.utc).isoformat()
        save_json(STATE_FILE, state)
        
        print(f"🗑️ Deleted {count} articles permanently")
        print(f"⏰ Last fetch time updated to now - future fetches won't redownload these")
    else:
        print("❌ Clear cancelled - inbox unchanged")

# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    """Parse command line arguments and run the appropriate command."""
    parser = argparse.ArgumentParser(
        description="9to5Google Article Reader - Personal Queue System",
        epilog="Commands: fetch (get new articles), review (show inbox), clear (delete all and update timestamp)"
    )
    parser.add_argument("command", choices=["fetch", "review", "clear"],
                       help="What to do: fetch new articles, review inbox, or clear all")
    args = parser.parse_args()
    
    if args.command == "fetch":
        fetch_all_new()
    elif args.command == "review":
        review()
    elif args.command == "clear":
        clear_inbox()

if __name__ == "__main__":
    main()