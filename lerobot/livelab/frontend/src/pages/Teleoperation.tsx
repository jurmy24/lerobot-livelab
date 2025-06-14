
import React from 'react';
import { useNavigate } from 'react-router-dom';
import VisualizerPanel from '@/components/control/VisualizerPanel';

const TeleoperationPage = () => {
  const navigate = useNavigate();

  const handleGoBack = () => {
    navigate('/');
  };

  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-2 sm:p-4">
      <div className="w-full h-[95vh] flex">
        <VisualizerPanel onGoBack={handleGoBack} className="lg:w-full" />
      </div>
    </div>
  );
};

export default TeleoperationPage;
