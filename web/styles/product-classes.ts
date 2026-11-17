import styles from './product.module.css'

/** Keep stable automation hooks alongside the module's locally scoped classes. */
export function productClass(value: string): string
export function productClass(value: string | undefined): string | undefined
export function productClass(value: string | undefined): string | undefined {
  if (!value) return value
  const scoped = value
    .split(/\s+/)
    .map(name => styles[name])
    .filter(Boolean)
  return scoped.length ? value + ' ' + scoped.join(' ') : value
}
