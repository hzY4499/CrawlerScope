You are helping build CrawlerScope, a crawler-specialized agent system based on AgentScope.

Rules:
1. Do not write one-off crawler scripts.
2. Build modular components.
3. Keep AgentScope as the agent control layer.
4. Put crawler-specific logic under crawler_scope/.
5. Do not commit secrets, cookies, tokens, browser storage states, or downloaded PDFs.
6. All future runs must write artifacts under runs/run_xxx/.
7. Do not bypass paywalls, CAPTCHAs, robots.txt, or access controls.
8. Prefer official APIs for paper metadata.
9. Keep tests for each module.
