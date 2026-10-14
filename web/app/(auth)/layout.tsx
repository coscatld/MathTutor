export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mt-standalone">
      <div className="mt-standalone-field mt-paper" aria-hidden="true" />
      {children}
    </div>
  );
}
