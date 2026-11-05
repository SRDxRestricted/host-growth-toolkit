import { Link, useLocation } from 'react-router-dom';
import './LegalPage.css';

const CONTENT = {
  privacy: {
    eyebrow: 'Privacy',
    title: 'Privacy notice',
    updated: 'Last updated: 4 November 2026',
    intro: 'This notice explains the information host It uses to provide its property-hosting tools.',
    sections: [
      ['Information we use', 'Account details such as your name, email address, and phone number; property and listing information you submit; uploaded listing photos; and messages or media you choose to send to our WhatsApp integration.'],
      ['Why we use it', 'We use this information to create and manage listings, generate pricing recommendations, show comparable properties, support calendar features, and provide the WhatsApp assistant.'],
      ['Service providers', 'The product may use hosting, messaging, mapping, and AI service providers to operate these features. Do not submit information you do not want processed by those services.'],
      ['Your choices', 'You can sign out at any time. For access, correction, or deletion requests, use the support channel provided with your host It account.'],
      ['Before launch', 'The business name, contact details, retention periods, jurisdictions, and processor list must be completed and reviewed before public launch.'],
    ],
  },
  terms: {
    eyebrow: 'Terms',
    title: 'Terms of use',
    updated: 'Last updated: 4 November 2026',
    intro: 'These terms describe the basic rules for using host It.',
    sections: [
      ['Using the service', 'You are responsible for the accuracy of the property, availability, and guest information you submit, and for complying with applicable rental, tax, safety, and platform rules.'],
      ['Pricing information', 'Pricing recommendations, demand signals, comparable listings, and map data are informational tools. They are not a guarantee of bookings, revenue, occupancy, or legal compliance. You remain responsible for every rate you publish.'],
      ['Your content', 'You confirm that you have the right to upload listing text and photos. Do not upload unlawful, misleading, infringing, or sensitive guest content.'],
      ['Acceptable use', 'Do not misuse the service, attempt to access another host’s information, interfere with service operation, or use the WhatsApp tools for spam.'],
      ['Before launch', 'These terms require the operating business identity, governing law, contact details, billing/refund terms, and a professional legal review before public launch.'],
    ],
  },
  cookies: {
    eyebrow: 'Cookies and storage',
    title: 'Cookie & storage notice',
    updated: 'Last updated: 4 November 2026',
    intro: 'host It currently uses browser storage to keep the product usable between pages.',
    sections: [
      ['Essential storage', 'The app stores signed-in user details and product preferences in your browser’s local storage, including the Portfolio Map prototype membership state.'],
      ['How to control it', 'Signing out clears the locally stored account session. You can also clear browser site data in your browser settings; this may reset product preferences.'],
      ['Third-party content', 'The Portfolio Map loads map tiles from OpenStreetMap. Other integrations, such as WhatsApp, may process information under their own terms and privacy notices.'],
      ['Before launch', 'Add a consent mechanism if analytics, advertising, or other non-essential cookies are introduced, and update this notice to reflect the final production setup.'],
    ],
  },
};

export default function LegalPage() {
  const section = useLocation().pathname.slice(1);
  const page = CONTENT[section] || CONTENT.privacy;

  return (
    <main className="legal-page">
      <nav className="legal-nav" aria-label="Legal navigation">
        <Link to="/" className="legal-brand">host It<span>.</span></Link>
        <Link to="/login" className="legal-sign-in">Sign in</Link>
      </nav>
      <article className="legal-card">
        <p className="legal-eyebrow">{page.eyebrow}</p>
        <h1>{page.title}</h1>
        <p className="legal-updated">{page.updated}</p>
        <p className="legal-intro">{page.intro}</p>
        <div className="legal-sections">
          {page.sections.map(([heading, copy]) => <section key={heading}><h2>{heading}</h2><p>{copy}</p></section>)}
        </div>
      </article>
      <footer className="legal-footer"><Link to="/privacy">Privacy</Link><Link to="/terms">Terms</Link><Link to="/cookies">Cookies</Link></footer>
    </main>
  );
}
