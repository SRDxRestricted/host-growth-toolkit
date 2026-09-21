import React, { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp, Sparkles, MessageCircle, LayoutDashboard } from 'lucide-react';
import './Landing.css';

const Landing = () => {
  const featuresRef = useRef(null);

  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry, index) => {
        if (entry.isIntersecting) {
          setTimeout(() => {
            entry.target.classList.add('visible');
          }, index * 150); // Stagger effect
          observer.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.1
    });

    const featureCards = document.querySelectorAll('.feature-card');
    featureCards.forEach((card) => {
      observer.observe(card);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <div className="landing-page">
      {/* Navigation */}
      <nav className="landing-nav">
        <div className="nav-container">
          <Link to="/" className="nav-logo">host It.</Link>
          <div className="nav-links">
            <a href="#features">Features</a>
            <a href="#pricing">Pricing</a>
            <a href="#about">About</a>
          </div>
          <Link to="/signup" className="nav-cta-btn">Get Started</Link>
        </div>
      </nav>

      {/* Hero Wrapper with Background */}
      <div className="hero-wrapper">
        {/* Hero Section */}
        <header className="hero-section">
        <div className="hero-container animate-fade-in-up">
          <h1 className="hero-headline">Price smarter. Host better.</h1>
          <p className="hero-subheadline">
            host It gives independent hosts the pricing intelligence and tools that used to be reserved for large property managers.
          </p>
          <div className="hero-ctas stagger-1">
            <Link to="/signup" className="btn-primary">Start Free</Link>
            <a href="#features" className="btn-secondary">See how it works</a>
          </div>
        </div>
      </header>

      {/* Features Grid Section */}
      <section id="features" className="features-section">
        <div className="features-container">
          <h2 className="section-title">Everything you need to grow</h2>
          <div className="features-grid">
            {/* Feature 1 */}
            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <TrendingUp className="feature-icon" />
              </div>
              <h3 className="feature-title">Dynamic Pricing</h3>
              <p className="feature-desc">
                Smart pricing recommendations based on local demand, events, and comparable listings. Set it and let host It watch the market for you.
              </p>
            </div>
            
            {/* Feature 2 */}
            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Sparkles className="feature-icon" />
              </div>
              <div className="feature-title-wrapper">
                <h3 className="feature-title">AI Listing Generator</h3>
              </div>
              <p className="feature-desc">
                Generate optimised titles and descriptions that convert.
              </p>
            </div>
            
            {/* Feature 3 */}
            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <MessageCircle className="feature-icon" />
              </div>
              <div className="feature-title-wrapper">
                <h3 className="feature-title">WhatsApp Booking Assistant</h3>
              </div>
              <p className="feature-desc">
                Let guests book and ask questions directly through WhatsApp.
              </p>
            </div>
            
            {/* Feature 4 */}
            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <LayoutDashboard className="feature-icon" />
              </div>
              <h3 className="feature-title">Host Dashboard</h3>
              <p className="feature-desc">
                Track bookings, earnings, and property performance in one clean view.
              </p>
            </div>
          </div>
        </div>
      </section>
      </div> {/* End of hero-wrapper */}

      {/* Social Proof / Stats Section */}
      <section className="stats-section">
        <div className="stats-container">
          <div className="stat-item">
            <h4 className="stat-value">500+</h4>
            <p className="stat-label">Active hosts</p>
          </div>
          <div className="stat-item">
            <h4 className="stat-value">£2.4M</h4>
            <p className="stat-label">Revenue optimised</p>
          </div>
          <div className="stat-item">
            <h4 className="stat-value">12%</h4>
            <p className="stat-label">Average uplift</p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="footer-container">
          <p className="footer-copy">© 2026 host It.</p>
          <div className="footer-links">
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
