# dslalpha nginx site

This is the production `dsalpha.roostbots.com` site config. It is tracked so the
SPA, API, SSE/WebSocket, relay, console proxy and cache rules survive a host
rebuild.

Install and reload:

```sh
install -m 0644 deploy/nginx/dsalpha.roostbots.com.conf \
  /etc/nginx/conf.d/dsalpha.roostbots.com.conf
nginx -t
nginx -s reload
```

The config expects:

```text
/opt/langalpha/web/dist          SPA build
/opt/langalpha/web/landing       landing page
/etc/nginx/ssl/dsalpha.roostbots.com/{fullchain.pem,key.pem}
backend on 127.0.0.1:8000
relay on 127.0.0.1:8788
roost-api on 127.0.0.1:18081
```

No TLS private key or credential is stored here. The `/ws/` location is what
lets the cloud-desktop VNC WebSocket through; it must use
`Connection "Upgrade"` rather than a map lookup on this host.
