import http from 'k6/http';
import { check, sleep } from 'k6';

// kubesynapse Operator Reconciliation Benchmark
// Measures operator API endpoints under load

export const options = {
  stages: [
    { duration: '30s', target: 5 },
    { duration: '2m', target: 20 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<1000'],
    http_req_failed: ['rate<0.05'],
  },
};

const BASE_URL = __ENV.OPERATOR_URL || 'http://localhost:8081';

export default function () {
  // Operator readiness probe
  const readyRes = http.get(`${BASE_URL}/ready`);
  check(readyRes, {
    'operator ready status valid': (r) => r.status === 200 || r.status === 503,
  });

  // Operator metrics endpoint
  const metricsRes = http.get(`${BASE_URL}/metrics`);
  check(metricsRes, {
    'metrics returns 200': (r) => r.status === 200,
    'metrics contains reconcile total': (r) => r.body.includes('KUBESYNAPSE_operator_reconcile_total'),
  });

  sleep(0.5);
}
