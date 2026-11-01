export type ConfigurationIdentity = {revision?: number; epoch?: string; preset_id: string};
export type ConfigurationReceipt = {revision?: number; current_revision?: number; epoch?: string; operation_id?: string; accepted?: boolean; persisted?: boolean};
export type SettingsOperation = Readonly<ConfigurationIdentity & {id: string; kind: "save" | "test" | "discover" | "remove"; generation: number}>;

/** One in-flight settings action; editing never changes its captured identity. */
export class SettingsOperations {
  generation = 0;
  active: SettingsOperation | null = null;
  constructor(private nextId = () => crypto.randomUUID()) {}
  edit() {this.generation++;}
  begin(kind: SettingsOperation["kind"], identity: ConfigurationIdentity): SettingsOperation | null {
    if (this.active) return null;
    return this.active = Object.freeze({...identity, kind, id: this.nextId(), generation: this.generation});
  }
  unchanged(operation: SettingsOperation) {return operation.generation === this.generation;}
  accepts(operation: SettingsOperation, receipt: ConfigurationReceipt, save = false): boolean {
    return this.active === operation && receipt.accepted === true && receipt.operation_id === operation.id
      && typeof receipt.epoch === "string" && Boolean(receipt.epoch) && (!operation.epoch || receipt.epoch === operation.epoch)
      && Number.isInteger(receipt.revision) && receipt.current_revision === receipt.revision
      && (save ? receipt.revision! > (operation.revision ?? -1) : receipt.revision === operation.revision);
  }
  finish(operation: SettingsOperation) {if (this.active === operation) this.active = null;}
}
