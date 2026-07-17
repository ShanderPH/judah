# Deployment and enforcement gate

No production deployment or mutation was performed in this run.

Required approved sequence:

1. authenticate/provide Railway access;
2. confirm staging and production service/environment identities;
3. remove production DB/Redis references from staging;
4. deploy migrations `support.0015` and `support.0016`;
5. deploy with shadow enabled and enforcement disabled;
6. validate one business day of decision telemetry;
7. explicitly approve and enable enforcement;
8. observe queue depth, heartbeat age, writer conflicts, and final-guard
   rejections.

Nathan must remain `auto_assign_enabled=true`. His out-of-office interval makes
him ineligible today; after the interval ends, HubSpot availability, working
hours, and the 30-second stability window return him online automatically.
