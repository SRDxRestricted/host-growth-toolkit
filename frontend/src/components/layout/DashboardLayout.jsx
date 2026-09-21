import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import ErrorBoundary from '../common/ErrorBoundary'
import './Layout.css'

const backgroundMap = {
  '/dashboard': 'https://images.unsplash.com/photo-1512918728675-ed5a9ecdebfd?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80',
  '/dashboard/pricing': 'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80',
  '/dashboard/calendar': 'https://images.unsplash.com/photo-1449844908441-8829872d2607?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80',
  '/dashboard/bookings': 'https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80',
  '/dashboard/listings': 'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?ixlib=rb-4.0.3&auto=format&fit=crop&w=2000&q=80',
}

function DashboardLayout() {
  const location = useLocation();
  const bgImage = backgroundMap[location.pathname] || backgroundMap['/dashboard'];

  return (
    <div className="dashboard-layout" style={{ backgroundImage: `url('${bgImage}')` }}>
      <Sidebar />
      <div className="dashboard-main">
        <Header />
        <main className="dashboard-content">
          <ErrorBoundary fallbackTitle="This page encountered an issue">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  )
}

export default DashboardLayout
