import { useEffect, useRef, useState, type ReactNode } from 'react';
import SvcIcon from '../components/SvcIcon';
import { useEscapeKey } from '../lib/useEscapeKey';

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export default function BottomSheet({ open, onClose, title, children }: Props) {
  const [render, setRender] = useState(false);
  const animRef = useRef(false);
  const sheetRef = useRef<HTMLDivElement>(null);

  useEscapeKey(onClose, open);

  // Sync open prop → render state with closing animation
  useEffect(() => {
    if (open) {
      setRender(true);
      animRef.current = false;
    } else if (render && !animRef.current) {
      animRef.current = true;
      const el = sheetRef.current;
      const scrim = document.querySelector('.bs-scrim') as HTMLElement;
      if (el) el.classList.add('bs-sheet--closing');
      if (scrim) scrim.classList.add('bs-scrim--closing');
      setTimeout(() => { setRender(false); animRef.current = false; }, 220);
    }
  }, [open, render]);

  // Body scroll lock
  useEffect(() => {
    if (render) document.body.style.overflow = 'hidden';
    else document.body.style.overflow = '';
    return () => { document.body.style.overflow = ''; };
  }, [render]);

  // iOS keyboard: visualViewport keeps sheet above keyboard
  useEffect(() => {
    if (!render) return;
    const el = sheetRef.current;
    if (!el) return;
    const adjust = () => {
      const vv = window.visualViewport;
      if (!vv) return;
      const kh = window.innerHeight - vv.height;
      if (kh > 80) {
        el.style.bottom = kh + 'px';
        el.style.maxHeight = Math.min(vv.height * 0.8, window.innerHeight - kh) + 'px';
      } else {
        el.style.bottom = '0px';
        el.style.maxHeight = '';
      }
    };
    window.visualViewport?.addEventListener('resize', adjust);
    return () => window.visualViewport?.removeEventListener('resize', adjust);
  }, [render]);

  const handleClose = () => {
    if (animRef.current) return;
    onClose(); // triggers parent to set open=false → triggers closing animation
  };

  if (!render) return null;

  return (
    <>
      <div className="bs-scrim" onClick={handleClose} />
      <div className="bs-sheet" ref={sheetRef}>
        <div className="bs-header">
          <span className="bs-handle" />
          <h3 className="bs-title">{title}</h3>
          <button className="bs-close" onClick={handleClose}><SvcIcon name="x" size={18} /></button>
        </div>
        <div className="bs-body">
          {children}
        </div>
      </div>
    </>
  );
}
