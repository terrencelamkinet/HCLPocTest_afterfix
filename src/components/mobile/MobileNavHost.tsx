import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import MobileBottomNav from './MobileBottomNav';
import AiSearchPanel from './AiSearchPanel';
import CameraScanSheet from './CameraScanSheet';
import NexusSmartAddModal from '../../modules/shared/NexusSmartAddModal';
import { ADD_CONFIGS, type AddModalConfig } from '../../modules/shared/add-modal-configs';
import { useToast } from '../v4/useToast';

/**
 * MobileNavHost — wires the whole mobile nav experience (≤768px only):
 *   bottom 5-tab nav + workspace/record/add/org sheets
 *   AI & Search dual panel (center button)
 *   Camera scan business card (Add banner / AI panel camera)
 *   Quick-add via existing NexusSmartAddModal (ADD_CONFIGS)
 */

export default function MobileNavHost() {
  const { t } = useTranslation();
  const toast = useToast();
  const [aiOpen, setAiOpen] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [smartAdd, setSmartAdd] = useState<{ config: AddModalConfig } | null>(null);

  const quickAdd = (recordType: string) => {
    const config = ADD_CONFIGS[recordType];
    if (config) {
      setSmartAdd({ config });
    } else {
      toast.showToast(`「${recordType}」快速新增尚未支援`);
    }
  };

  const handleScanCard = () => setCameraOpen(true);

  return (
    <>
      <MobileBottomNav
        onOpenAiSearch={() => setAiOpen(true)}
        onNavInteract={() => setAiOpen(false)}
        onScanCard={handleScanCard}
        onQuickAdd={quickAdd}
      />
      <AiSearchPanel
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        onScanCard={() => { setAiOpen(false); setCameraOpen(true); }}
        onRequestOpen={() => setAiOpen(true)}
      />
      <CameraScanSheet
        open={cameraOpen}
        onClose={() => setCameraOpen(false)}
        onSaved={(label) => toast.showToast(`✅ ${label} 已入庫`)}
      />
      {smartAdd && (
        <NexusSmartAddModal
          config={smartAdd.config}
          open
          onClose={() => setSmartAdd(null)}
          onCreated={() => { setSmartAdd(null); toast.showToast(t('common.saved', '已儲存')); }}
        />
      )}
    </>
  );
}
