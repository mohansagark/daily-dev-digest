import os
import re
import random
import time
import requests
import json
import hashlib
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
from slugify import slugify
from dotenv import load_dotenv
from yaml_utils import yaml_safe_value

# Load environment variables
load_dotenv()
FEEDS = os.getenv("FEED_SOURCES", "").split(",")

MAX_PER_FEED = 5
MAX_TOTAL = 20
OUTPUT_DIR = "digests"
DUPLICATES_FILE = "processed_articles.json"

# Content strategy based on time of day
def get_content_strategy():
    """Determine content strategy based on current time"""
    current_hour = datetime.now().hour
    
    strategies = {
        "morning": {
            "time_range": "6-11",
            "focus": ["javascript", "frontend", "react", "vue", "angular", "typescript", "node.js", "coding-tips"],
            "style": "energetic and practical",
            "description": "Technical tutorials and coding tips to start the day"
        },
        "afternoon": {
            "time_range": "12-17", 
            "focus": ["backend", "databases", "api", "devops", "cloud", "architecture", "performance", "security"],
            "style": "detailed and informative",
            "description": "Deep technical content for focused work hours"
        },
        "evening": {
            "time_range": "18-23",
            "focus": ["ux", "ui", "design", "productivity", "tools", "career", "soft-skills", "trends"],
            "style": "thoughtful and reflective",
            "description": "Design, career, and industry insights for evening reading"
        },
        "night": {
            "time_range": "0-5",
            "focus": ["tutorials", "learning", "fundamentals", "concepts", "theory", "best-practices"],
            "style": "educational and foundational",
            "description": "Educational content for late-night learners"
        }
    }
    
    if 6 <= current_hour <= 11:
        return strategies["morning"]
    elif 12 <= current_hour <= 17:
        return strategies["afternoon"]
    elif 18 <= current_hour <= 23:
        return strategies["evening"]
    else:
        return strategies["night"]

def load_processed_articles():
    """Load previously processed articles to prevent duplicates"""
    if os.path.exists(DUPLICATES_FILE):
        try:
            with open(DUPLICATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_processed_articles(processed_articles):
    """Save processed articles to prevent future duplicates"""
    with open(DUPLICATES_FILE, 'w', encoding='utf-8') as f:
        json.dump(processed_articles, f, indent=2, ensure_ascii=False)

def get_article_hash(article):
    """Generate unique hash for article to detect duplicates"""
    content = f"{article['title']}{article['link']}{article['content'][:200]}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def extract_tags_from_content(title, content, strategy_focus):
    """Extract tags from article content without AI"""
    text = f"{title} {content}".lower()
    
    # Common tech terms to look for
    tech_terms = {
        'javascript': ['javascript', 'js', 'node.js', 'nodejs', 'es6', 'es2015'],
        'python': ['python', 'django', 'flask', 'pandas', 'numpy'],
        'react': ['react', 'reactjs', 'jsx', 'hooks', 'redux'],
        'vue': ['vue', 'vuejs', 'nuxt'],
        'angular': ['angular', 'angularjs', 'typescript'],
        'css': ['css', 'scss', 'sass', 'tailwind', 'bootstrap'],
        'html': ['html', 'html5', 'dom', 'semantic'],
        'ui': ['ui', 'user interface', 'interface design'],
        'ux': ['ux', 'user experience', 'usability', 'accessibility'],
        'design': ['design', 'designer', 'visual', 'typography'],
        'backend': ['backend', 'server', 'api', 'database'],
        'frontend': ['frontend', 'client-side', 'browser'],
        'mobile': ['mobile', 'android', 'ios', 'app'],
        'web': ['web', 'website', 'webapp', 'progressive'],
        'performance': ['performance', 'optimization', 'speed', 'loading'],
        'security': ['security', 'authentication', 'authorization', 'vulnerability'],
        'devops': ['devops', 'docker', 'kubernetes', 'ci/cd', 'deployment'],
        'cloud': ['cloud', 'aws', 'azure', 'gcp', 'serverless'],
        'database': ['database', 'sql', 'mongodb', 'postgresql', 'mysql'],
        'tools': ['tools', 'editor', 'vscode', 'github', 'git'],
        'career': ['career', 'job', 'interview', 'developer', 'programmer'],
        'productivity': ['productivity', 'workflow', 'automation', 'efficiency']
    }
    
    found_tags = []
    
    # Check for tech terms
    for tag, keywords in tech_terms.items():
        for keyword in keywords:
            if keyword in text:
                found_tags.append(tag)
                break
    
    # Add strategy-specific tags if they match
    for focus_tag in strategy_focus:
        if focus_tag.lower() in text and focus_tag not in found_tags:
            found_tags.append(focus_tag)
    
    # Remove duplicates and limit to 5
    return list(set(found_tags))[:5]

def generate_summary(content, max_sentences=3):
    """Generate a simple summary by taking first few sentences"""
    # Clean HTML tags
    clean_content = re.sub(r'<[^>]+>', '', content)
    
    # Split into sentences
    sentences = re.split(r'[.!?]+', clean_content)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]
    
    # Take first few sentences
    summary_sentences = sentences[:max_sentences]
    return '. '.join(summary_sentences) + '.'

def generate_key_takeaways(content, title):
    """Generate key takeaways from content"""
    # Look for numbered lists, bullet points, or key phrases
    takeaways = []
    
    # Common patterns that indicate key points
    patterns = [
        r'(?:key|important|main|primary|essential).*?(?:point|aspect|feature|benefit|advantage)',
        r'(?:first|second|third|finally|lastly|importantly)',
        r'(?:remember|note|consider|keep in mind)',
        r'(?:tip|trick|best practice|recommendation)'
    ]
    
    sentences = re.split(r'[.!?]+', content)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 20:  # Avoid very short sentences
            for pattern in patterns:
                if re.search(pattern, sentence, re.IGNORECASE):
                    takeaways.append(sentence)
                    break
            if len(takeaways) >= 5:
                break
    
    # If no specific takeaways found, create generic ones
    if not takeaways:
        takeaways = [
            f"Understanding {title} is essential for modern web development",
            "This technology/approach can improve your development workflow",
            "Consider implementing these concepts in your next project",
            "Stay updated with the latest trends and best practices"
        ]
    
    return takeaways[:5]

def filter_articles_by_strategy(articles, strategy):
    """Filter articles based on current content strategy"""
    filtered = []
    strategy_keywords = strategy["focus"]
    
    for article in articles:
        # Check if article content matches strategy focus
        article_text = f"{article['title']} {article['content']}".lower()
        
        # Score article based on keyword matches
        score = 0
        for keyword in strategy_keywords:
            if keyword.lower() in article_text:
                score += 1
        
        # Add articles with at least one keyword match
        if score > 0:
            article['strategy_score'] = score
            filtered.append(article)
    
    # Sort by strategy score (highest first)
    filtered.sort(key=lambda x: x.get('strategy_score', 0), reverse=True)
    return filtered

def fetch_full_article_content(url):
    """Fetch full article content from URL"""
    try:
        print(f"📖 Fetching full content from: {url}")
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'aside', 'header']):
            element.decompose()
        
        # Try to find main content
        content_selectors = [
            'article',
            '.post-content',
            '.entry-content', 
            '.content',
            'main',
            '.article-body',
            '.post-body'
        ]
        
        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break
        
        if not content:
            content = soup.find('body')
        
        if content:
            # Extract text content
            text = content.get_text()
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:3000]  # Limit to first 3000 chars
        
        return ""
        
    except Exception as e:
        print(f"⚠️ Error fetching full content from {url}: {e}")
        return ""

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
            
            # Try to get full article content
            full_content = fetch_full_article_content(link)
            if full_content:
                body = full_content
            
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

def create_mdx_content(article, strategy, slug):
    """Create MDX content without AI - using scraped content directly"""
    
    # Generate metadata
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M")
    
    # Extract tags from content
    tags = extract_tags_from_content(article['title'], article['content'], strategy['focus'])
    
    # Generate summary
    summary = generate_summary(article['content'])
    
    # Generate key takeaways
    key_takeaways = generate_key_takeaways(article['content'], article['title'])
    
    # Create subtitle based on strategy
    subtitle_templates = {
        "morning": f"Essential insights for developers to start the day",
        "afternoon": f"Deep technical analysis for focused development",
        "evening": f"Thoughtful perspectives on design and career growth", 
        "night": f"Educational foundations for continuous learning"
    }
    
    strategy_key = "evening" if "evening" in strategy['description'].lower() else "morning"
    if "afternoon" in strategy['description'].lower():
        strategy_key = "afternoon"
    elif "night" in strategy['description'].lower():
        strategy_key = "night"
    
    subtitle = subtitle_templates.get(strategy_key, "Professional insights for developers")
    
    # Create frontmatter
frontmatter = f"""---
title: {yaml_safe_value(article['title'])}
subtitle: {yaml_safe_value(subtitle)}
summary: {yaml_safe_value(summary)}
slug: {yaml_safe_value(slug)}
date: {yaml_safe_value(current_date)}
time: {yaml_safe_value(current_time)}
content_strategy: {yaml_safe_value(strategy['description'])}
writing_style: {yaml_safe_value(strategy['style'])}
tags: {json.dumps(tags)}  # tags is a list, JSON is safe!
image_suggestion: {yaml_safe_value(f'Professional illustration representing {article["title"]}')}
source_url: {yaml_safe_value(article['link'])}
published_date: {yaml_safe_value(article['published'])}
---
"""
    
    # Format the main content
    content = article['content']
    
    # Split content into paragraphs
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    
    # Create structured content
    main_content = f"""# {article['title']}

## {subtitle}

### Summary
{summary}

---

"""
    
    # Add main content in readable format
    for i, paragraph in enumerate(paragraphs):
        if len(paragraph) > 50:  # Only include substantial paragraphs
            main_content += f"{paragraph}\n\n"
        if i > 10:  # Limit to reasonable length
            break
    
    # Add key takeaways
    main_content += f"""## Key Takeaways

"""
    
    for i, takeaway in enumerate(key_takeaways, 1):
        main_content += f"{i}. {takeaway}\n"
    
    # Add footer
    main_content += f"""
---

*This content was curated using the **{strategy['description']}** strategy ({strategy['time_range']} hours) with a {strategy['style']} focus.*

*Original source: [{article['title']}]({article['link']})*

*Tags: {', '.join(tags)}*
"""
    
    return frontmatter + main_content

def save_to_mdx(article, strategy, slug):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{slug}.mdx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    mdx_content = create_mdx_content(article, strategy, slug)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(mdx_content)
    print(f"✅ Saved: {filepath}")

def main():
    print("📥 Fetching articles (No AI - Direct scraping approach)...")
    
    # Get current content strategy
    strategy = get_content_strategy()
    current_time = datetime.now().strftime("%H:%M")
    print(f"⏰ Current time: {current_time}")
    print(f"🎯 Content strategy: {strategy['description']}")
    print(f"✍️  Writing style: {strategy['style']}")
    print(f"🏷️  Focus areas: {', '.join(strategy['focus'])}")
    
    # Load processed articles to prevent duplicates
    processed_articles = load_processed_articles()
    print(f"📚 Loaded {len(processed_articles)} previously processed articles")
    
    # Fetch articles from feeds
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

    # Filter out duplicates
    new_articles = []
    for article in all_articles:
        article_hash = get_article_hash(article)
        if article_hash not in processed_articles:
            new_articles.append(article)
            article['hash'] = article_hash
        else:
            print(f"⚠️ Skipping duplicate: {article['title'][:50]}...")
    
    print(f"🆕 Found {len(new_articles)} new articles (filtered {len(all_articles) - len(new_articles)} duplicates)")
    
    if not new_articles:
        print("❌ No new articles found. All articles have been processed before.")
        return
    
    # Filter articles by content strategy
    strategy_articles = filter_articles_by_strategy(new_articles, strategy)
    print(f"🎯 Found {len(strategy_articles)} articles matching current strategy")
    
    # If no articles match strategy, fall back to general selection
    if not strategy_articles:
        print("⚠️ No articles match current strategy. Using general selection.")
        strategy_articles = new_articles
    
    # Select articles for processing
    selected = strategy_articles[:min(4, len(strategy_articles))]
    successful_generations = 0
    
    for article in selected:
        print(f"📝 Processing: {article['title']}")
        slug = slugify(article['title'])[:40]
        save_to_mdx(article, strategy, slug)
        
        # Mark article as processed
        processed_articles[article['hash']] = {
            'title': article['title'],
            'link': article['link'],
            'processed_date': datetime.now().isoformat(),
            'strategy_used': strategy['description']
        }
        
        successful_generations += 1
        time.sleep(random.randint(1, 3))  # Brief pause between articles
    
    # Save updated processed articles
    save_processed_articles(processed_articles)
    
    print(f"🎉 Successfully generated {successful_generations} blog posts using {strategy['description']} strategy!")
    print(f"📝 Total processed articles: {len(processed_articles)}")
    print("💡 No AI used - all content sourced directly from original articles!")

if __name__ == "__main__":
    main()
