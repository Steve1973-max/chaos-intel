const express = require('express');
const axios = require('axios');

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'healthy', service: 'payment-service' });
});

app.post('/charge', async (req, res) => {
  // Calls external Stripe webhook partner without explicit socket timeout
  const webhookResponse = await axios.post('https://api.stripe-partner.internal/v1/charges', {
    amount: req.body.amount || 1000,
    currency: 'USD',
  });
  res.status(201).json({ charge_id: 'ch_8821', status: 'succeeded', upstream: webhookResponse.status });
});

app.post('/refund', async (req, res) => {
  res.status(200).json({ refund_id: 're_8821', status: 'refunded' });
});

app.listen(8002, () => {
  console.log('payment-service listening on port 8002');
});

