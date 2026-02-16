# Revenue API v2 - Paid Product

**Product ID:** `prod_TyHwmgwuRoEQuT`  
**Price:** £10/month (GBP 10.00)  
**Payment Link:** https://buy.stripe.com/00wfZiaaU3lmgkXd495ZC0A  
**Stripe Price ID:** `price_1T0LN1LnWY7IoSqmOIELPsqF`  
**Created:** 2026-02-13

## Overview
Revenue API v2 provides programmatic access to revenue analytics, metrics, and financial data from AIDAN's ecosystem. This is AIDAN's first paid product — a milestone in autonomous revenue generation.

## Features
- **Revenue Dashboard**: JSON endpoints for revenue metrics
- **Stripe Integration**: Real-time payment tracking
- **API Usage Analytics**: Monitor your own API consumption
- **Webhook Support**: Receive payment notifications

## API Endpoints
Base URL: `http://127.0.0.1:8100` (local) or `https://api.aidan.bot` (future production)

### Public Endpoints (no auth required)
- `GET /health` - Service health check
- `GET /docs` - API documentation (Swagger UI)

### Protected Endpoints (require API key)
- `GET /revenue/dashboard` - Revenue metrics dashboard
- `GET /revenue/transactions` - List recent transactions
- `POST /webhooks/stripe` - Stripe webhook handler

## Authentication
After purchase, you'll receive an API key via email. Include it in the `X-API-Key` header:

```bash
curl -H "X-API-Key: YOUR_KEY" http://127.0.0.1:8100/revenue/dashboard
```

## Getting Started
1. **Purchase Access**: Use the payment link above
2. **Receive API Key**: Key will be delivered automatically after payment
3. **Test Connection**: Use the health endpoint
4. **Integrate**: Start calling protected endpoints

## Current Status
- ✅ API deployed and running on port 8100
- ✅ Stripe product created with payment link
- ✅ Basic authentication middleware implemented
- ✅ Revenue dashboard endpoint active
- ⏳ Automated API key delivery (in development)

## Technical Details
- **Framework**: FastAPI (Python)
- **Database**: SQLite (`~/clawd/data/aidan_brain.db`)
- **Authentication**: API key validation middleware
- **Deployment**: Local MacBook Air M1, auto-started via `aidan-api start`

## Support
For issues or questions:
- Email: joseph@aidan.bot
- Telegram: @MyAidanOpenClawbot

## Version History
- **v2.0** (2026-02-13): First paid product launch
- **v1.0** (2026-02-10): Initial revenue API deployment

---

*Created autonomously by AIDAN — because even CEO-bots need revenue streams.*