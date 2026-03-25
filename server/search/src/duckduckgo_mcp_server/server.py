from mcp.server.fastmcp import FastMCP, Context
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import urllib.parse
import sys
import traceback
import asyncio
from datetime import datetime, timedelta
import time
import re
import os

def get_proxy_settings() -> Dict[str, str] | None:
    """从环境变量获取代理配置"""
    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    
    # 如果没有配置环境变量，尝试使用常见的本地代理端口
    if not http_proxy and not https_proxy:
        # 常见代理端口检测 (Clash, v2ray 等)
        for port in [7890, 7897, 10809, 1080]:
            try:
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    if s.connect_ex(('127.0.0.1', port)) == 0:
                        proxy_url = f"http://127.0.0.1:{port}"
                        print(f"Auto-detected local proxy at {proxy_url}", file=sys.stderr)
                        return {"http://": proxy_url, "https://": proxy_url}
            except:
                pass
        return None

    proxies = {}
    if http_proxy:
        proxies["http://"] = http_proxy
    if https_proxy:
        proxies["https://"] = https_proxy
    
    return proxies if proxies else None

@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str
    position: int


class RateLimiter:
    def __init__(self, requests_per_minute: int = 30, burst_threshold: int = 5):
        self.requests_per_minute = requests_per_minute
        self.burst_threshold = burst_threshold
        self.requests = []
        self.last_warning_time = 0

    async def acquire(self):
        now = datetime.now()
        # Remove requests older than 1 minute
        self.requests = [
            req for req in self.requests if now - req < timedelta(minutes=1)
        ]

        if len(self.requests) >= self.requests_per_minute:
            # 添加智能退避策略
            wait_time = 60 - (now - self.requests[0]).total_seconds()
            if wait_time > 0:
                # 记录警告，避免重复日志
                current_time = time.time()
                if current_time - self.last_warning_time > 60:  # 每分钟最多警告一次
                    print(f"⚠️ 搜索速率限制触发，等待 {wait_time:.1f} 秒", file=sys.stderr)
                    self.last_warning_time = current_time
                await asyncio.sleep(wait_time)

        # 突发流量控制：如果短时间内请求过多，增加额外延迟
        recent_requests = [
            req for req in self.requests 
            if now - req < timedelta(seconds=10)
        ]
        
        if len(recent_requests) >= self.burst_threshold:
            # 突发流量控制，增加随机延迟
            import random
            extra_delay = random.uniform(0.5, 2.0)
            await asyncio.sleep(extra_delay)

        self.requests.append(now)


class DuckDuckGoSearcher:
    BASE_URL = "https://html.duckduckgo.com/html/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://duckduckgo.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.session_data = {
            'last_search_time': 0,
            'search_count': 0,
            'error_count': 0
        }
        self.proxies = get_proxy_settings()

    def format_results_for_llm(self, results: List[SearchResult]) -> str:
        """Format results in a natural language style that's easier for LLMs to process"""
        if not results:
            return "No results were found for your search query. This could be due to DuckDuckGo's bot detection or the query returned no matches. Please try rephrasing your search or try again in a few minutes."

        output = []
        output.append(f"Found {len(results)} search results:\n")

        for result in results:
            output.append(f"{result.position}. {result.title}")
            output.append(f"   URL: {result.link}")
            output.append(f"   Summary: {result.snippet}")
            output.append("")  # Empty line between results

        return "\n".join(output)

    async def search(
        self, query: str, ctx: Context, max_results: int = 10
    ) -> List[SearchResult]:
        try:
            # 更新会话数据
            current_time = time.time()
            if current_time - self.session_data['last_search_time'] > 60:
                self.session_data['search_count'] = 0
                self.session_data['error_count'] = 0
            
            self.session_data['last_search_time'] = current_time
            self.session_data['search_count'] += 1
            
            # Apply rate limiting
            await self.rate_limiter.acquire()

            # 查询预处理：移除特殊字符，避免触发反爬虫
            clean_query = re.sub(r'[^\w\s\-_.]', ' ', query).strip()
            if len(clean_query) < 2:
                clean_query = query
            
            # Create form data for POST request
            data = {
                "q": clean_query,
                "b": "",
                "kl": "",
                "df": ""  # 添加额外的表单字段
            }

            await ctx.info(f"Searching DuckDuckGo for: {clean_query}")

            # 添加随机延迟，模拟人类行为
            if self.session_data['search_count'] > 3:
                import random
                delay = random.uniform(0.5, 1.5)
                await asyncio.sleep(delay)

            print(f"DEBUG: Starting HTTP POST to {self.BASE_URL}...", file=sys.stderr)
            client_kwargs = {}
            if self.proxies:
                client_kwargs["proxies"] = self.proxies
            try:
                client = httpx.AsyncClient(**client_kwargs)
            except TypeError:
                fallback_kwargs = {}
                if self.proxies:
                    proxy_url = self.proxies.get("https://") or self.proxies.get("http://")
                    if proxy_url:
                        fallback_kwargs["proxy"] = proxy_url
                client = httpx.AsyncClient(**fallback_kwargs)

            async with client:
                try:
                    response = await client.post(
                        self.BASE_URL, data=data, headers=self.HEADERS, timeout=5.0, follow_redirects=True
                    )
                    print(f"DEBUG: HTTP POST returned status {response.status_code}", file=sys.stderr)
                    response.raise_for_status()
                except Exception as e:
                    print(f"DEBUG: HTTP POST failed: {e}", file=sys.stderr)
                    raise
                
                # 重置错误计数
                self.session_data['error_count'] = 0

            # Parse HTML response
            print("DEBUG: Parsing HTML...", file=sys.stderr)
            soup = BeautifulSoup(response.text, "html.parser")
            if not soup:
                await ctx.error("Failed to parse HTML response")
                return []

            results = []
            for result in soup.select(".result"):
                title_elem = result.select_one(".result__title")
                if not title_elem:
                    continue

                link_elem = title_elem.find("a")
                if not link_elem:
                    continue

                title = link_elem.get_text(strip=True)
                link = link_elem.get("href", "")

                # Skip ad results
                if "y.js" in link:
                    continue

                # Clean up DuckDuckGo redirect URLs
                if link.startswith("//duckduckgo.com/l/?uddg="):
                    link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])

                snippet_elem = result.select_one(".result__snippet")
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                results.append(
                    SearchResult(
                        title=title,
                        link=link,
                        snippet=snippet,
                        position=len(results) + 1,
                    )
                )

                if len(results) >= max_results:
                    break

            await ctx.info(f"Successfully found {len(results)} results")
            return results

        except httpx.TimeoutException:
            self.session_data['error_count'] += 1
            error_msg = f"搜索请求超时 (第{self.session_data['error_count']}次错误)"
            await ctx.error(error_msg)
            # 如果连续错误过多，增加额外等待时间
            if self.session_data['error_count'] >= 3:
                await asyncio.sleep(5)
            return []
        except httpx.HTTPStatusError as e:
            self.session_data['error_count'] += 1
            error_msg = f"HTTP错误 {e.response.status_code}: {str(e)}"
            await ctx.error(error_msg)
            
            # 针对不同状态码的处理
            if e.response.status_code == 429:  # 速率限制
                await ctx.error("触发速率限制，等待30秒")
                await asyncio.sleep(30)
            elif e.response.status_code >= 500:  # 服务器错误
                await asyncio.sleep(10)
            elif e.response.status_code == 403:  # 被禁止
                await ctx.error("可能被反爬虫检测，建议降低请求频率")
                await asyncio.sleep(15)
            
            return []
        except httpx.HTTPError as e:
            self.session_data['error_count'] += 1
            await ctx.error(f"HTTP错误发生: {str(e)}")
            if self.session_data['error_count'] >= 3:
                await asyncio.sleep(3)
            return []
        except Exception as e:
            self.session_data['error_count'] += 1
            await ctx.error(f"搜索意外错误: {str(e)}")
            traceback.print_exc(file=sys.stderr)
            if self.session_data['error_count'] >= 3:
                await asyncio.sleep(2)
            return []


class BaiduSearcher:
    BASE_URL = "https://www.baidu.com/s"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0"
    }

    def __init__(self):
        self.rate_limiter = RateLimiter(requests_per_minute=20)

    def format_results_for_llm(self, results: List[SearchResult]) -> str:
        """Format results in a natural language style"""
        if not results:
            return "No results were found for your search query on Baidu."

        output = []
        output.append(f"Found {len(results)} search results from Baidu:\n")

        for result in results:
            output.append(f"{result.position}. {result.title}")
            output.append(f"   URL: {result.link}")
            output.append(f"   Summary: {result.snippet}")
            output.append("")

        return "\n".join(output)

    async def search(
        self, query: str, ctx: Context, max_results: int = 10
    ) -> List[SearchResult]:
        try:
            await self.rate_limiter.acquire()
            await ctx.info(f"Searching Baidu for: {query}")

            params = {"wd": query}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL, params=params, headers=self.HEADERS, timeout=15.0
                )
                response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            
            # Baidu search results are usually in containers with class 'c-container'
            for result_elem in soup.select(".c-container"):
                # Title
                title_elem = result_elem.select_one("h3")
                if not title_elem:
                    continue
                
                link_elem = title_elem.find("a")
                if not link_elem:
                    continue
                
                title = link_elem.get_text(strip=True)
                link = link_elem.get("href", "")
                
                # Snippet - try different classes Baidu uses
                snippet = ""
                snippet_elem = result_elem.select_one(".c-abstract") or \
                              result_elem.select_one(".content-right_8Zs40") or \
                              result_elem.select_one(".c-span18") # Fallback
                
                if snippet_elem:
                    snippet = snippet_elem.get_text(strip=True)

                results.append(
                    SearchResult(
                        title=title,
                        link=link,
                        snippet=snippet,
                        position=len(results) + 1,
                    )
                )

                if len(results) >= max_results:
                    break

            await ctx.info(f"Successfully found {len(results)} results on Baidu")
            return results
            
        except Exception as e:
            await ctx.error(f"Baidu search error: {str(e)}")
            return []


class WebContentFetcher:
    def __init__(self):
        self.rate_limiter = RateLimiter(requests_per_minute=20)

    async def fetch_and_parse(self, url: str, ctx: Context) -> str:
        """Fetch and parse content from a webpage"""
        try:
            await self.rate_limiter.acquire()

            await ctx.info(f"Fetching content from: {url}")

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    follow_redirects=True,
                    timeout=30.0,
                )
                response.raise_for_status()

            # Parse the HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # 智能内容提取：优先提取主要内容区域
            main_content = None
            
            # 尝试找到主要内容区域
            for selector in ['main', 'article', '.content', '.main-content', '#content', '#main-content']:
                main_content = soup.select_one(selector)
                if main_content:
                    break
            
            # 如果没有找到主要内容区域，使用整个body
            if not main_content:
                main_content = soup.find('body') or soup

            # Remove script and style elements
            for element in main_content(["script", "style", "nav", "header", "footer", "aside", "advertisement"]):
                element.decompose()

            # Get the text content
            text = main_content.get_text()

            # Clean up the text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = " ".join(chunk for chunk in chunks if chunk)

            # Remove extra whitespace and special characters
            text = re.sub(r"\s+", " ", text).strip()
            
            # 智能截断：优先保留重要内容
            max_length = 8000
            if len(text) > max_length:
                # 尝试在句子边界截断
                sentences = re.split(r'[.!?]+', text)
                truncated = ""
                for sentence in sentences:
                    if len(truncated) + len(sentence) + 2 < max_length:
                        truncated += sentence + ". "
                    else:
                        break
                
                if len(truncated) < max_length * 0.7:  # 如果句子截断太少，直接字符截断
                    text = text[:max_length] + "... [内容已截断]"
                else:
                    text = truncated.strip() + "... [内容已截断]"

            await ctx.info(
                f"成功获取并解析内容 ({len(text)} 字符)"
            )
            return text

        except httpx.TimeoutException:
            await ctx.error(f"Request timed out for URL: {url}")
            return "Error: The request timed out while trying to fetch the webpage."
        except httpx.HTTPError as e:
            await ctx.error(f"HTTP error occurred while fetching {url}: {str(e)}")
            return f"Error: Could not access the webpage ({str(e)})"
        except Exception as e:
            await ctx.error(f"Error fetching content from {url}: {str(e)}")
            return f"Error: An unexpected error occurred while fetching the webpage ({str(e)})"


# Initialize FastMCP server
mcp = FastMCP("ddg-search")
searcher = DuckDuckGoSearcher()
baidu_searcher = BaiduSearcher()
fetcher = WebContentFetcher()


@mcp.tool()
async def search(query: str, ctx: Context, max_results: int = 20) -> str:
    """
    Search DuckDuckGo (fallback to Baidu) and return formatted results.

    Args:
        query: The search query string
        max_results: Maximum number of results to return (default: 10)
        ctx: MCP context for logging
    """
    try:
        # Try DDG first
        results = await searcher.search(query, ctx, max_results)
        if results:
            return searcher.format_results_for_llm(results)
        
        # Fallback to Baidu
        await ctx.info("DuckDuckGo returned no results, trying Baidu...")
        results = await baidu_searcher.search(query, ctx, max_results)
        return baidu_searcher.format_results_for_llm(results)
        
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return f"An error occurred while searching: {str(e)}"


@mcp.tool()
async def fetch_content(url: str, ctx: Context) -> str:
    """
    Fetch and parse content from a webpage URL.

    Args:
        url: The webpage URL to fetch content from
        ctx: MCP context for logging
    """
    return await fetcher.fetch_and_parse(url, ctx)


def main():
    mcp.run()


if __name__ == "__main__":
    mcp.run(transport="stdio")
