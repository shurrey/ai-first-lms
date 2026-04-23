-- Add microcredential to node_kind enum
ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'microcredential';
-- Add contributes_to to edge_kind enum
ALTER TYPE edge_kind ADD VALUE IF NOT EXISTS 'contributes_to';
