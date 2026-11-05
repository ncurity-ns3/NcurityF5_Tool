"""Shared HTML table layout for OS upgrade reports."""

TABLE_COLGROUP = (
    '<colgroup><col class="col-item"><col class="col-result">'
    '<col class="col-remark"></colgroup>'
)

MAIN_TABLE_CSS = """
table.main{border-collapse:collapse;width:100%;max-width:100%;table-layout:fixed;}
table.main col.col-item{width:18%;}
table.main col.col-result{width:58%;}
table.main col.col-remark{width:24%;}
table.main th,table.main td{border:1px solid #bbb;padding:8px 10px;vertical-align:top;}
table.main thead th{background:#dce6f0;font-weight:600;}
table.main tbody th{background:#eef2f6;font-weight:600;font-size:0.92em;
  padding:8px 8px;word-break:break-word;line-height:1.3;}
table.main td.result{word-break:break-word;}
table.main td.remark{color:#555;font-size:0.88em;word-break:break-word;line-height:1.35;}
table.main td.nested{padding:6px 8px;}
.scroll{display:block;overflow-x:auto;overflow-y:visible;
  -webkit-overflow-scrolling:touch;max-width:100%;}
table.grid{border-collapse:collapse;width:max-content;min-width:100%;table-layout:auto;}
table.grid th,table.grid td{border:1px solid #bbb;padding:6px 10px;text-align:left;
  vertical-align:top;white-space:nowrap;font-size:0.92em;}
table.grid th{background:#dce6f0;font-weight:600;}
table.grid tr:nth-child(even){background:#f8fafc;}
table.grid.grid-arp{min-width:720px;}
table.grid.grid-mac{min-width:360px;}
table.grid.grid-ping{min-width:480px;}
"""
