"""Presets fuer proprietäre Unternehmenssysteme (REST).

Jedes Preset beschreibt, wie ein System per REST angesprochen wird:
- auth:       bearer | basic | none
- datasets_path / datasets_list:  Endpoint + JSON-Pfad der Item-Liste (Katalog)
- search_path / search_list:      Such-Endpoint mit {q} und {limit} (GapSearchAgent)
- item:         Mapping id/title/text/url (Dotted Paths; url darf {base} und Item-Felder enthalten)

SAP HANA und Databricks-SQL-Warehouses werden NICHT ueber REST angebunden,
sondern ueber den sql-Connector (hdbcli / databricks-connector, siehe README).
"""

PRESETS: dict[str, dict] = {
    "jira": {
        "auth": "basic",
        "datasets_path": "/rest/api/2/search?jql=order%20by%20created%20desc&maxResults=100&fields=summary,description,attachment",
        "datasets_list": "issues",
        "search_path": "/rest/api/2/search?jql={q}&maxResults={limit}&fields=summary,description,attachment",
        "search_list": "issues",
        "item": {"id": "key", "title": "fields.summary", "text": "fields.description", "url": "{base}/browse/{key}"},
    },
    "graph": {  # Outlook / Microsoft 365 via Microsoft Graph
        "auth": "bearer",
        "base_url_default": "https://graph.microsoft.com",
        "datasets_path": "/v1.0/me/messages?$top=100&$select=subject,bodyPreview,receivedDateTime,from,webLink",
        "datasets_list": "value",
        "search_path": '/v1.0/me/messages?$search="{q}"&$top={limit}&$select=subject,bodyPreview,webLink,from',
        "search_list": "value",
        "item": {"id": "id", "title": "subject", "text": "bodyPreview", "url": "webLink"},
    },
    "powerbi": {
        "auth": "bearer",
        "base_url_default": "https://api.powerbi.com",
        "datasets_path": "/v1.0/myorg/datasets",
        "datasets_list": "value",
        "search_path": "/v1.0/myorg/datasets?$filter=contains(name,'{q}')",
        "search_list": "value",
        "item": {"id": "id", "title": "name", "text": "description", "url": "webUrl"},
    },
    "databricks": {  # REST nur fuer Uebersicht; Daten laufen ueber sql-Connector (Warehouse)
        "auth": "bearer",
        "datasets_path": "/api/2.0/warehouses",
        "datasets_list": "warehouses",
        "search_path": "/api/2.0/warehouses",
        "search_list": "warehouses",
        "item": {"id": "id", "title": "name", "text": "jdbc_url", "url": "{base}"},
    },
    "generic": {  # Polarion, Planisware (OPX), Hebbia, Facton, Serdia, eigene SaaS-APIs ...
        "auth": "bearer",
        "base_url_default": None,
        "datasets_path": None,  # ueber Config setzen
        "datasets_list": "value",
        "search_path": None,    # ueber Config setzen, mit {q} und {limit}
        "search_list": "value",
        "item": {"id": "id", "title": "title", "text": "description", "url": "url"},
    },
}
