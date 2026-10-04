"""合成题的技能族与场景（QWEN_PLAN §4.1）。出题模型只拿到这里的抽象描述，看不到任何 TB 题（防污染）。"""
FAMILIES = {
    "log-regex": "Extracting and aggregating information from semi-structured text logs with regular expressions, where lines are "
                 "irregular (mixed formats, noise lines, tricky edge cases inside fields) and the requested summary has an exact format.",
    "data-transform": "Transforming structured data between formats (CSV, JSON, INI-like, fixed-width text) into a precisely specified "
                      "output, including normalization rules and edge cases (quoting, missing fields, duplicates, ordering, rounding).",
    "port-program": "Porting a small program written in another language (C, awk, bash, or a tiny language fully described in the task) "
                    "to Python so that it produces byte-identical output for the same inputs, including error and edge-case behavior.",
    "local-service": "Implementing a small HTTP service on localhost that follows a written JSON API specification, including error "
                     "responses and state; the service must keep running in the background after the agent finishes.",
    "git-repair": "Repairing or recovering state in a local git repository (lost commits, a bad merge or rebase, rewritten history, "
                  "wrong branch pointers, accidentally committed files) so that it matches a precisely described target state.",
    "sqlite-query": "Writing SQL against a provided SQLite database to answer a precisely described question with an exact output format, "
                    "or rewriting a slow query into an equivalent faster one that returns identical rows.",
}
DOMAINS = ["warehouse inventory", "weather stations", "library loans", "flight schedules", "payroll", "sports league results",
           "IoT sensor readings", "e-commerce orders", "hospital appointments", "code review comments", "bus transit feeds",
           "university course enrollment", "restaurant reservations", "bank transactions", "game server events",
           "package deliveries", "energy meter readings", "museum ticketing", "recipe ingredients", "job scheduler runs",
           "chess club tournaments", "hotel bookings", "bird survey counts", "podcast download stats", "car rental fleet"]
