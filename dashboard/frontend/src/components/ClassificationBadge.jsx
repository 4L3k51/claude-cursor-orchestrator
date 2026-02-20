import React from 'react';

const ClassificationBadge = ({ classification, count }) => {
  const getClassificationClass = () => {
    switch (classification?.toLowerCase()) {
      case 'architectural':
        return 'classification-architectural';
      case 'implementation':
        return 'classification-implementation';
      case 'clean_pass':
        return 'classification-clean';
      case 'ambiguous':
      case 'pending':
      default:
        return 'classification-pending';
    }
  };

  return (
    <span className={`classification-badge ${getClassificationClass()}`}>
      {classification}{count !== undefined && `: ${count}`}
    </span>
  );
};

export default ClassificationBadge;
