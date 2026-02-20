import React from 'react';

const StatusBadge = ({ status }) => {
  const getStatusClass = () => {
    switch (status?.toLowerCase()) {
      case 'success':
      case 'completed':
        return 'badge-success';
      case 'failed':
        return 'badge-failed';
      case 'partial':
      case 'running':
        return 'badge-partial';
      default:
        return 'badge-default';
    }
  };

  return (
    <span className={`badge ${getStatusClass()}`}>
      {status || 'unknown'}
    </span>
  );
};

export default StatusBadge;
