# Fixture provenance

`product.json` is **synthetic**, modelling a Shopee item/model payload. It is not
an authenticated recording and does not establish current Shopee compatibility.
A live attempt on 2026-10-12 redirected to Login Required. Once authenticated
access is available, validate the parser against the actual page response and
add a sanitized fixture containing only item identity, name, currency, models,
prices, and stock. Never commit headers, cookies, account data, or full HAR files.
