import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000/api',
  timeout: 30000,
});

export const getRuns = async (params = {}) => {
  const response = await api.get('/runs', { params });
  return response.data;
};

export const getRun = async (runId) => {
  const response = await api.get(`/runs/${runId}`);
  return response.data;
};

export const getRunSteps = async (runId) => {
  const response = await api.get(`/runs/${runId}/steps`);
  return response.data;
};

export const getStepDetail = async (runId, stepNumber) => {
  const response = await api.get(`/runs/${runId}/steps/${stepNumber}`);
  return response.data;
};

export const getStats = async () => {
  const response = await api.get('/stats');
  return response.data;
};

export const triggerIngest = async (force = false) => {
  const response = await api.post('/ingest', null, { params: { force } });
  return response.data;
};

export const getPatterns = async () => {
  const response = await api.get('/patterns');
  return response.data;
};

export default api;
