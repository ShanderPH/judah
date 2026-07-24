# Staging domain assessment

Date: 2026-07-14

## Summary

- Validated `https://judah-admin.staging.febrate.com`: DNS/TLS and Vercel routing work, but the deployment is protected by Vercel SSO (`302`).
- The current webapp flow is correct for Visitor Identification: it authenticates the Judah session server-side, creates the HubSpot token server-side, and then loads the inline widget.
- A new domain does not require a HubSpot app credential or redirect-URL change for this static-auth app.

## Required configuration checks

1. Link the domain to the `staging` branch/custom environment in Vercel and ensure it has `JUDAH_API_URL`, `HUBSPOT_SANDBOX_ACCESS_TOKEN`, and `NEXT_PUBLIC_HUBSPOT_PORTAL_ID=51734496`.
2. In HubSpot, add `judah-admin.staging.febrate.com` and `/sandbox-chat` to the chatflow target rule if the flow is not configured for all pages.
3. Log in again on the staging domain: Judah auth cookies are host-only and are not shared from `judah-admin.febrate.com`.
4. Decide whether Vercel SSO protection should remain enabled for staging testers.

## Separate end-to-end blocker

The sandbox webhook still targets Railway and `conversation.newMessage` is inactive. For Salomao to receive chat messages, configure the HubSpot webhook with the public Render backend URL and activate that subscription. This is independent of the frontend staging domain.

## Changes made

No application, HubSpot, Vercel, or Render configuration was changed during this assessment.
