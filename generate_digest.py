import os
import re
import random
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
from slugify import slugify
from openai import OpenAI
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FEEDS = os.getenv("FEED_SOURCES", "").split(",")

MAX_PER_FEED = 5
MAX_TOTAL = 20
OUTPUT_DIR = "digests"

client = OpenAI(api_key=OPENAI_API_KEY)

def fetch_articles_from_feed(url):
    print(f"🔗 Fetching: {url}")
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, features="xml")
        items = soup.find_all("item")[:MAX_PER_FEED]
        articles = []
        for item in items:
            title = item.title.text
            link = item.link.text
            pub_date = item.pubDate.text if item.find("pubDate") else ""
            content = item.find("description") or item.find("content:encoded")
            body = content.text if content else ""
            articles.append({
                "title": title.strip(),
                "link": link.strip(),
                "published": pub_date.strip(),
                "content": re.sub(r"<.*?>", "", body).strip()
            })
        return articles
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return []

def generate_blog_content(article):
    print(f"🧠 Generating blog post for: {article['title']}")
    prompt = f"""
You are a professional tech blogger. Based on the following article, provide a structured response in JSON format with these exact keys:

- "subtitle": A compelling subtitle for the article
- "summary": A 2-3 sentence summary of the article
- "tags": An array of 3-5 relevant tags (e.g., ["javascript", "web-development", "react"])
- "image_suggestion": A description of a relevant image for the article
- "content": The main blog post content in markdown format (400-600 words, educational and engaging)
- "key_takeaways": An array of 3-5 key takeaways from the article

Original Article:
Title: {article['title']}
URL: {article['link']}
Content: {article['content'][:2000]}

Respond only with valid JSON.
    """

    try:
        res = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful developer blog writer. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        response_content = res.choices[0].message.content.strip()
        
        # Clean up the response to ensure it's valid JSON
        if response_content.startswith('```json'):
            response_content = response_content[7:-3]
        elif response_content.startswith('```'):
            response_content = response_content[3:-3]
        
        try:
            return json.loads(response_content)
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON response for: {article['title']}")
            return None
            
    except Exception as e:
        print(f"❌ GPT generation error for: {article['title']}\n{e}")
        return None

def create_mdx_content(article, blog_data, slug):
    """Create properly formatted MDX content with frontmatter"""
    
    # Generate current date
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # Create frontmatter
    frontmatter = f"""---
title: "{article['title']}"
subtitle: "{blog_data['subtitle']}"
summary: "{blog_data['summary']}"
slug: "{slug}"
date: "{current_date}"
tags: {json.dumps(blog_data['tags'])}
image_suggestion: "{blog_data['image_suggestion']}"
source_url: "{article['link']}"
---

"""
    
    # Create the main content
    main_content = f"""# {article['title']}

## {blog_data['subtitle']}

### Summary
{blog_data['summary']}

---

{blog_data['content']}

## Key Takeaways

"""
    
    # Add key takeaways as a numbered list
    for i, takeaway in enumerate(blog_data['key_takeaways'], 1):
        main_content += f"{i}. {takeaway}\n"
    
    # Add footer
    main_content += f"""
---

*This post was generated from the original article: [{article['title']}]({article['link']})*

*Tags: {', '.join(blog_data['tags'])}*
"""
    
    return frontmatter + main_content

def save_to_mdx(article, blog_data, slug):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{slug}.mdx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    mdx_content = create_mdx_content(article, blog_data, slug)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(mdx_content)
    print(f"✅ Saved: {filepath}")

def main():
    print("📥 Fetching articles...")
    all_articles = []
    for feed_url in FEEDS:
        if len(all_articles) >= MAX_TOTAL:
            break
        articles = fetch_articles_from_feed(feed_url)
        all_articles.extend(articles)

    print(f"📄 Fetched {len(all_articles)} articles")
    if not all_articles:
        print("❌ No articles found. Exiting.")
        return

    selected = random.sample(all_articles, min(4, len(all_articles)))
    successful_generations = 0
    
    for article in selected:
        blog_data = generate_blog_content(article)
        if blog_data:
            slug = slugify(article['title'])[:40]
            save_to_mdx(article, blog_data, slug)
            successful_generations += 1
        else:
            print(f"⚠️ Failed to generate: {article['title']}")
        time.sleep(random.randint(3, 5))  # Sleep to avoid rate-limiting
    
    print(f"🎉 Successfully generated {successful_generations} blog posts!")

if __name__ == "__main__":
    main()