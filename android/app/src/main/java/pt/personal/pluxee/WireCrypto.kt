package pt.personal.pluxee

import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Compatibility with the official mobile wire format, not encryption for local storage. */
object WireCrypto {
    private val key = "S0d3x0_34/25;Z245678936987410321".toByteArray(Charsets.UTF_8)
    private const val alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    private val random = SecureRandom()
    fun encrypt(value: String, iv: String = buildString { repeat(16) { append(alphabet[random.nextInt(alphabet.length)]) } }): String {
        require(iv.length == 16 && iv.all { it.code < 128 })
        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv.toByteArray(Charsets.UTF_8)))
        return Base64.getEncoder().encodeToString(cipher.doFinal(value.toByteArray(Charsets.UTF_8))) + iv
    }
}
