//! SHA-256 (FIPS 180-4), implemented in-tree.
//!
//! It lives here because `axiom-cli` deliberately builds with **no third-party
//! dependency** (`Cargo.toml`: "No third-party dependencies. The distribution layer
//! must build from a pinned toolchain with no network fetch") while
//! `contracts/axiom-cli-distribution-contract.md` section 6 requires a sha256 to be
//! verified for **every artifact before it is used**.
//!
//! Only the digest is implemented. There is no signature, no key material and no
//! cryptographic protocol in this file: `docs/20-VERSION-CHECK-UPDATE-RELEASE.md`
//! section 3 requires signed channel metadata to be verified through a maintained,
//! reviewed library, and forbids writing that protocol here. The trust layer of this
//! module therefore pins a *digest* (see `channel.rs`); it does not pretend to verify
//! a signature.

use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

const INITIAL_STATE: [u32; 8] = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

/// Streaming SHA-256 state.
pub struct Sha256 {
    state: [u32; 8],
    block: [u8; 64],
    used: usize,
    total: u64,
}

impl Default for Sha256 {
    fn default() -> Sha256 {
        Sha256::new()
    }
}

impl Sha256 {
    /// A fresh hasher in its initial state.
    pub fn new() -> Sha256 {
        Sha256 {
            state: INITIAL_STATE,
            block: [0u8; 64],
            used: 0,
            total: 0,
        }
    }

    /// Absorb more input. Any chunking of the same byte stream yields the same digest.
    pub fn update(&mut self, mut bytes: &[u8]) {
        self.total = self.total.wrapping_add(bytes.len() as u64);
        while !bytes.is_empty() {
            let take = (64 - self.used).min(bytes.len());
            self.block[self.used..self.used + take].copy_from_slice(&bytes[..take]);
            self.used += take;
            bytes = &bytes[take..];
            if self.used == 64 {
                let block = self.block;
                compress(&mut self.state, &block);
                self.used = 0;
            }
        }
    }

    /// Finalize and return the 32-byte digest.
    pub fn finish(mut self) -> [u8; 32] {
        let bits = self.total.wrapping_mul(8);
        let mut tail: Vec<u8> = Vec::with_capacity(72);
        tail.push(0x80);
        while (self.used + tail.len()) % 64 != 56 {
            tail.push(0);
        }
        tail.extend_from_slice(&bits.to_be_bytes());
        self.update(&tail);
        let mut out = [0u8; 32];
        for (chunk, word) in out.chunks_exact_mut(4).zip(self.state.iter()) {
            chunk.copy_from_slice(&word.to_be_bytes());
        }
        out
    }
}

fn compress(state: &mut [u32; 8], block: &[u8; 64]) {
    let mut schedule = [0u32; 64];
    for (slot, chunk) in schedule.iter_mut().zip(block.chunks_exact(4)) {
        *slot = u32::from_be_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
    }
    for index in 16..64 {
        let first = schedule[index - 15];
        let sigma0 = first.rotate_right(7) ^ first.rotate_right(18) ^ (first >> 3);
        let second = schedule[index - 2];
        let sigma1 = second.rotate_right(17) ^ second.rotate_right(19) ^ (second >> 10);
        schedule[index] = schedule[index - 16]
            .wrapping_add(sigma0)
            .wrapping_add(schedule[index - 7])
            .wrapping_add(sigma1);
    }

    let mut a = state[0];
    let mut b = state[1];
    let mut c = state[2];
    let mut d = state[3];
    let mut e = state[4];
    let mut f = state[5];
    let mut g = state[6];
    let mut h = state[7];

    for (constant, word) in K.iter().zip(schedule.iter()) {
        let big_sigma1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
        let choose = (e & f) ^ ((!e) & g);
        let temp1 = h
            .wrapping_add(big_sigma1)
            .wrapping_add(choose)
            .wrapping_add(*constant)
            .wrapping_add(*word);
        let big_sigma0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
        let majority = (a & b) ^ (a & c) ^ (b & c);
        let temp2 = big_sigma0.wrapping_add(majority);

        h = g;
        g = f;
        f = e;
        e = d.wrapping_add(temp1);
        d = c;
        c = b;
        b = a;
        a = temp1.wrapping_add(temp2);
    }

    for (slot, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
        *slot = slot.wrapping_add(value);
    }
}

/// Digest of one byte slice.
pub fn digest(bytes: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finish()
}

/// Lowercase hex encoding.
pub fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        // `from_digit` cannot fail for base 16 and a nibble.
        out.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
        out.push(char::from_digit(u32::from(byte & 0x0f), 16).unwrap_or('0'));
    }
    out
}

/// Lowercase hex digest of one byte slice.
pub fn digest_hex(bytes: &[u8]) -> String {
    hex(&digest(bytes))
}

/// Lowercase hex digest of a file, streamed so a large artifact is never held in memory.
pub fn file_hex(path: &Path) -> io::Result<String> {
    let mut handle = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; 64 * 1024];
    loop {
        let read = handle.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex(&hasher.finish()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_the_published_vectors() {
        let cases: [(&str, &str); 4] = [
            ("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            ("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
            (
                "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
                "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
            ),
            (
                "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu",
                "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1",
            ),
        ];
        for (input, expected) in cases {
            assert_eq!(digest_hex(input.as_bytes()), expected, "input={input:?}");
        }
    }

    #[test]
    fn chunking_does_not_change_the_digest() {
        let payload: Vec<u8> = (0u8..=255).cycle().take(1000).collect();
        let one_shot = digest_hex(&payload);
        for chunk in [1usize, 3, 7, 63, 64, 65, 127, 129] {
            let mut hasher = Sha256::new();
            for part in payload.chunks(chunk) {
                hasher.update(part);
            }
            assert_eq!(hex(&hasher.finish()), one_shot, "chunk={chunk}");
        }
    }

    #[test]
    fn exactly_sixty_four_bytes_is_the_block_boundary() {
        // 55 and 56 bytes are the padding-length boundary; 63/64/65 cross the block edge.
        for size in [54usize, 55, 56, 57, 63, 64, 65, 119, 120, 121] {
            let payload = vec![b'a'; size];
            let one_shot = digest_hex(&payload);
            let mut hasher = Sha256::new();
            hasher.update(&payload[..size / 2]);
            hasher.update(&payload[size / 2..]);
            assert_eq!(hex(&hasher.finish()), one_shot, "size={size}");
        }
    }
}
