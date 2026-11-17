
import { productClass } from "@/styles/product-classes";
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className={productClass("mt-standalone")}>
      <div className={productClass("mt-standalone-field mt-paper")} aria-hidden="true" />
      {children}
    </div>
  );
}
