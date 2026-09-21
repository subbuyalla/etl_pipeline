export default function LoadingSpinner({ text = 'Loading data...' }) {
  return (
    <div className="loading-wrap">
      <div className="spinner" />
      <span>{text}</span>
    </div>
  );
}
