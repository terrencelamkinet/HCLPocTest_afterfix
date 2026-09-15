import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import ChatboxPanel from './ChatboxPanel';

export default function Layout() {
  const closeMobile = () => {
    const shell = document.getElementById('appShell');
    if (shell) shell.classList.remove('mobile-open');
    window.dispatchEvent(new CustomEvent('close-mobile-menu'));
  };

  return (
    <div className="app-shell" id="appShell">
      <div className="scrim" onClick={closeMobile}></div>
      <Sidebar />
      <Header />
      <main className="main-content">
        <Outlet />
      </main>
      <ChatboxPanel />
    </div>
  );
}
