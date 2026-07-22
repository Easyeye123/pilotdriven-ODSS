# AWS Location Service setup runbook

## 1. Select region

Choose the region in which PilotDriven/ODSS will operate. Confirm Maps V2, Hybrid dynamic maps and the required static-map fallback are available for the selected provider/account configuration.

## 2. Create the API key

Using the Amazon Location console:

1. Open **API keys**.
2. Create a key such as `pilotdriven-odss-maps`.
3. Restrict resources to the Maps V2 provider resource.
4. Restrict actions to required `geo-maps` read actions.
5. Configure expiration/rotation.
6. Configure client restrictions for local and production origins.
7. Store the key securely.

CLI concept:

```bash
aws location create-key \
  --key-name pilotdriven-odss-maps \
  --restrictions '{
    "AllowActions": ["geo-maps:*"],
    "AllowResources": ["arn:aws:geo-maps:<region>::provider/default"]
  }' \
  --no-expiry
```

Tighten the action set during production hardening.

## 3. Local environment

Copy the example environment:

```bash
cp pilotdriven_odss_dashboard/.env.example .env
```

Populate:

```text
ODSS_MAP_PROVIDER=aws-location
AWS_REGION=ap-southeast-2
AWS_LOCATION_API_KEY=<secret>
ODSS_MAP_STYLE=Hybrid
ODSS_MAP_LANGUAGE=en
ODSS_MAP_FALLBACK=static
ODSS_MAP_SCREENSHOT_TIMEOUT_SECONDS=30
ODSS_MAP_PRINT_BASE_URL=http://127.0.0.1:8000
```

Do not commit `.env`.

## 4. Verify style descriptor

```bash
curl "https://maps.geo.${AWS_REGION}.amazonaws.com/v2/styles/Hybrid/descriptor?key=${AWS_LOCATION_API_KEY}"
```

Use `ap-southeast-2` for the accepted Hybrid plus static Satellite chain.
Amazon Location regions backed by GrabMaps (`ap-southeast-1` and
`ap-southeast-5`) expose Standard/Monochrome instead and are rejected by the
ODSS configuration when Hybrid or the Satellite static fallback is selected.

A valid response is a MapLibre-compatible style document.

## 5. Production secret storage

Store the API key in AWS Secrets Manager or an approved secret/config service. Inject it into:

- the web/backend configuration endpoint;
- the report worker;
- the static fallback client.

For a public browser map, use a referrer-restricted web key. Do not use broad AWS credentials in the browser.

## 6. Rotation

1. Create a new key.
2. Deploy the new key.
3. Verify dashboard and PDF capture.
4. Revoke the prior key.
5. Record the change in the audit log.

## 7. Monitoring

Track:

- failed style/tile requests;
- GetStaticMap HTTP errors;
- throttling;
- render time;
- screenshot timeout;
- fallback rate;
- provider cost.
