import http from 'k6/http';
import { check, sleep } from 'k6';

// KubeSynth API Gateway Load Test
// Usage: k6 run tests/performance/api-gateway.js

export const options = {
  stages: [
    { duration: '1m', target: 10 },   // Ramp up
    { duration: '3m', target: 50 },   // Steady state
    { duration: '1m', target: 100 },  // Stress test
    { duration: '1m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms
    http_req_failed: ['rate<0.01'],    // Error rate under 1%
  },
};

const BASE_URL = __ENV.API_URL || 'http://localhost:8080';
const AUTH_TOKEN = __ENV.API_TOKEN || 'test-token';

export default function () {
  const headers = {
    'Authorization': `Bearer ${AUTH_TOKEN}`,
    'Content-Type': 'application/json',
  };

  // Test 1: Health endpoint (no auth required)
  const healthRes = http.get(`${BASE_URL}/api/health`);
  check(healthRes, {
    'health status is 200': (r) => r.status === 200,
    'health response time < 100ms': (r) => r.timings.duration < 100,
  });

  // Test 2: List agents
  const agentsRes = http.get(`${BASE_URL}/api/agents`, { headers });
  check(agentsRes, {
    'agents status is 200 or 404': (r) => r.status === 200 || r.status === 404,
  });

  // Test 3: Ready check
  const readyRes = http.get(`${BASE_URL}/api/ready`);
  check(readyRes, {
    'ready status is 200 or 503': (r) => r.status === 200 || r.status === 503,
  });

  sleep(1);
}
