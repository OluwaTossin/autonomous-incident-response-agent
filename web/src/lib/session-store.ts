import "server-only";

import { Pool, type PoolClient } from "pg";
import { webConfig } from "./config";

export interface LoginTransactionRecord {
  idHash: string;
  stateHash: string;
  encryptedPayload: Buffer;
  returnPath: string;
  createdAt: Date;
  expiresAt: Date;
}

export interface StoredSession {
  idHash: string;
  userId: string;
  providerIssuer: string;
  providerSubject: string;
  displayName: string;
  email: string;
  encryptedTokens: Buffer;
  csrfHash: string;
  accessExpiresAt: Date;
  createdAt: Date;
  lastSeenAt: Date;
  inactivityExpiresAt: Date;
  absoluteExpiresAt: Date;
  revokedAt: Date | null;
  version: number;
}

export interface SessionStore {
  createLoginTransaction(record: LoginTransactionRecord): Promise<void>;
  consumeLoginTransaction(idHash: string, now: Date): Promise<LoginTransactionRecord | null>;
  createSession(session: StoredSession): Promise<void>;
  getAndTouchSession(
    idHash: string,
    now: Date,
    inactivitySeconds: number,
  ): Promise<StoredSession | null>;
  replaceTokens(
    idHash: string,
    expectedVersion: number,
    encryptedTokens: Buffer,
    accessExpiresAt: Date,
  ): Promise<boolean>;
  revokeSession(idHash: string, now: Date): Promise<void>;
}

let pool: Pool | undefined;

function databasePool(): Pool {
  pool ??= new Pool({ connectionString: webConfig().databaseUrl, max: 10 });
  return pool;
}

function rowToSession(row: Record<string, unknown>): StoredSession {
  return {
    idHash: String(row.id_hash),
    userId: String(row.user_id),
    providerIssuer: String(row.provider_issuer),
    providerSubject: String(row.provider_subject),
    displayName: String(row.display_name),
    email: String(row.email),
    encryptedTokens: row.encrypted_tokens as Buffer,
    csrfHash: String(row.csrf_hash),
    accessExpiresAt: row.access_expires_at as Date,
    createdAt: row.created_at as Date,
    lastSeenAt: row.last_seen_at as Date,
    inactivityExpiresAt: row.inactivity_expires_at as Date,
    absoluteExpiresAt: row.absolute_expires_at as Date,
    revokedAt: (row.revoked_at as Date | null) ?? null,
    version: Number(row.version),
  };
}

export class PostgresSessionStore implements SessionStore {
  constructor(private readonly sessions: Pool = databasePool()) {}

  async createLoginTransaction(record: LoginTransactionRecord): Promise<void> {
    await this.sessions.query(
      `INSERT INTO oauth_login_transactions
       (id_hash, state_hash, encrypted_payload, return_path, created_at, expires_at)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        record.idHash,
        record.stateHash,
        record.encryptedPayload,
        record.returnPath,
        record.createdAt,
        record.expiresAt,
      ],
    );
  }

  async consumeLoginTransaction(
    idHash: string,
    now: Date,
  ): Promise<LoginTransactionRecord | null> {
    const result = await this.sessions.query(
      `UPDATE oauth_login_transactions SET consumed_at = $2
       WHERE id_hash = $1 AND consumed_at IS NULL AND expires_at > $2
       RETURNING *`,
      [idHash, now],
    );
    const row = result.rows[0];
    if (!row) return null;
    return {
      idHash: row.id_hash,
      stateHash: row.state_hash,
      encryptedPayload: row.encrypted_payload,
      returnPath: row.return_path,
      createdAt: row.created_at,
      expiresAt: row.expires_at,
    };
  }

  async createSession(session: StoredSession): Promise<void> {
    await this.sessions.query(
      `INSERT INTO browser_sessions
       (id_hash, user_id, provider_issuer, provider_subject, display_name, email,
        encrypted_tokens, csrf_hash, access_expires_at, created_at, last_seen_at,
        inactivity_expires_at, absolute_expires_at, revoked_at, version)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
      [
        session.idHash,
        session.userId,
        session.providerIssuer,
        session.providerSubject,
        session.displayName,
        session.email,
        session.encryptedTokens,
        session.csrfHash,
        session.accessExpiresAt,
        session.createdAt,
        session.lastSeenAt,
        session.inactivityExpiresAt,
        session.absoluteExpiresAt,
        session.revokedAt,
        session.version,
      ],
    );
  }

  async getAndTouchSession(
    idHash: string,
    now: Date,
    inactivitySeconds: number,
  ): Promise<StoredSession | null> {
    const client = await this.sessions.connect();
    try {
      await client.query("BEGIN");
      const current = await client.query(
        "SELECT * FROM browser_sessions WHERE id_hash = $1 FOR UPDATE",
        [idHash],
      );
      const row = current.rows[0];
      if (
        !row ||
        row.revoked_at ||
        row.inactivity_expires_at <= now ||
        row.absolute_expires_at <= now
      ) {
        if (row && !row.revoked_at) {
          await client.query(
            "UPDATE browser_sessions SET revoked_at = $2 WHERE id_hash = $1",
            [idHash, now],
          );
        }
        await client.query("COMMIT");
        return null;
      }
      const touched = await client.query(
        `UPDATE browser_sessions
         SET last_seen_at = $2,
             inactivity_expires_at = LEAST(
               absolute_expires_at,
               $2 + ($3 * interval '1 second')
             )
         WHERE id_hash = $1 RETURNING *`,
        [idHash, now, inactivitySeconds],
      );
      await client.query("COMMIT");
      return rowToSession(touched.rows[0]);
    } catch (error) {
      await this.rollback(client);
      throw error;
    } finally {
      client.release();
    }
  }

  async replaceTokens(
    idHash: string,
    expectedVersion: number,
    encryptedTokens: Buffer,
    accessExpiresAt: Date,
  ): Promise<boolean> {
    const result = await this.sessions.query(
      `UPDATE browser_sessions
       SET encrypted_tokens = $3, access_expires_at = $4, version = version + 1
       WHERE id_hash = $1 AND version = $2 AND revoked_at IS NULL`,
      [idHash, expectedVersion, encryptedTokens, accessExpiresAt],
    );
    return result.rowCount === 1;
  }

  async revokeSession(idHash: string, now: Date): Promise<void> {
    await this.sessions.query(
      "UPDATE browser_sessions SET revoked_at = COALESCE(revoked_at, $2) WHERE id_hash = $1",
      [idHash, now],
    );
  }

  private async rollback(client: PoolClient): Promise<void> {
    try {
      await client.query("ROLLBACK");
    } catch {
      // Preserve the original error; the pool discards broken clients.
    }
  }
}

export async function closeSessionPoolForTests(): Promise<void> {
  await pool?.end();
  pool = undefined;
}
