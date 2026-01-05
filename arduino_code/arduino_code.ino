// avris_miner.ino - Arduino miner for AVRIS blockchain with sha1 hash

#include <Arduino.h>
#include "sha1.h" // Built-in Arduino library

// Mining parameters
String currentJob = "";
String targetPattern = "00"; // Default difficulty
String lastProof = "";
String prevHash = "";
int blockIndex = 0;
int difficulty = 1;


// Mining statistics
unsigned long hashCount = 0;
unsigned long lastStatsTime = 0;
unsigned long startTime = 0;

// Proper hash function with sha1
String calculatesha1Hash(String last_proof, String proof) {
    // Create the input string exactly as in Python: f'{last_proof}{proof}'
    String input = last_proof + proof;
    
    // Reset sha1 context
    Sha1.init();
    
    // Add the input data
    Sha1.print(input);
    
    // Get the hash result (40 hex characters)
    uint8_t* hashBytes = Sha1.result();
    
    // Convert to hex string
    char hexBuffer[41];  // 40 hex chars + null terminator
    for (int i = 0; i < 20; i++) {  // sha1 is 20 bytes
        sprintf(hexBuffer + (i * 2), "%02x", hashBytes[i]);
    }
    hexBuffer[40] = '\0';
    
    return String(hexBuffer);
}

void setup() {
    Serial.begin(115200);
    while (!Serial) {
        ; // Wait for serial port to connect
    }
    
    // Seed random with floating analog pin
    randomSeed(analogRead(A0));
    
    startTime = millis();
    Serial.println("READY");
    Serial.println("AVRIS Miner v0.1 - sha1 Hash - Waiting for job...");
}

void loop() {
    // Check for incoming jobs from Python bridge
    if (Serial.available() > 0) {
        String message = Serial.readStringUntil('\n');
        message.trim();
        processMessage(message);
    }
    
    // Mine if we have a job
    if (currentJob == "MINING") {
        mine();
    }
    
    // Send stats every 10 seconds
    if (millis() - lastStatsTime > 10000) {
        sendStats();
        lastStatsTime = millis();
    }
    
    delay(1); // Small delay
}

void processMessage(String message) {
    if (message.startsWith("JOB:")) {
        // Format: JOB:index:last_proof:prev_hash:difficulty:target
        int colons[5];
        int colonCount = 0;
        
        for (int i = 0; i < message.length() && colonCount < 5; i++) {
            if (message.charAt(i) == ':') {
                colons[colonCount++] = i;
            }
        }
        
        if (colonCount == 5) {
            blockIndex = message.substring(colons[0]+1, colons[1]).toInt();
            lastProof = message.substring(colons[1]+1, colons[2]);
            prevHash = message.substring(colons[2]+1, colons[3]);
            difficulty = message.substring(colons[3]+1, colons[4]).toInt();
            
            // Build target pattern based on difficulty
            targetPattern = "";
            for (int i = 0; i < difficulty; i++) {
                targetPattern += "0";
            }
            
            Serial.print("JOB #");
            Serial.println(blockIndex);
            Serial.print("Last proof: ");
            Serial.println(lastProof);
            Serial.print("Difficulty: ");
            Serial.println(difficulty);
            Serial.print("Target: ");
            Serial.println(targetPattern);
            
            // Reset hash counter for new job
            hashCount = 0;
            startTime = millis();
            
            currentJob = "MINING";
        }
    }
    else if (message == "STOP") {
        currentJob = "";
        Serial.println("Stopped mining");
    }
    else if (message == "PING") {
        Serial.println("PONG");
    }
    else if (message == "SUCCESS") {
        Serial.println("Block accepted! Waiting for next job...");
        currentJob = "";
    }
    else if (message.startsWith("REJECTED:")) {
        Serial.print("Block rejected: ");
        Serial.println(message.substring(9));
        currentJob = "";
    }
}

void mine() {
    // Generate nonce (start with random, then sequential)
    static unsigned long nonce = 0;
    if (nonce == 0) {
        nonce = random(1, 1000000);
    } else {
        nonce++;  // Try sequential nonces
    }
    
    // Convert nonce to string
    String proofStr = String(nonce);
    
    // Calculate sha1 hash
    String candidateHash = calculatesha1Hash(lastProof, proofStr);
    
    hashCount++;
    
    // Show progress every 1000 hashes
    if (hashCount % 1000 == 0) {
        unsigned long elapsed = millis() - startTime;
        float hashrate = (elapsed > 0) ? (hashCount * 1000.0 / elapsed) : 0;
        
        Serial.print("Hashes: ");
        Serial.print(hashCount);
        Serial.print(", Nonce: ");
        Serial.print(nonce);
        Serial.print(", Rate: ");
        Serial.print(hashrate);
        Serial.print(" H/s, Hash: ");
        Serial.println(candidateHash.substring(0, 8) + "...");
    }
    
    // Check if hash meets target (starts with targetPattern)
    if (candidateHash.startsWith(targetPattern)) {
        unsigned long elapsed = millis() - startTime;
        float hashrate = (elapsed > 0) ? (hashCount * 1000.0 / elapsed) : 0;
        
        Serial.print("FOUND ");
        Serial.print(nonce);
        Serial.print(" ");
        Serial.println(candidateHash);
        Serial.print("Found in ");
        Serial.print(elapsed / 1000.0);
        Serial.print("s (");
        Serial.print(hashrate);
        Serial.println(" H/s)");
        
        // Reset nonce for next job
        nonce = 0;
        // Pause mining until we get a new job
        currentJob = "";
    }
    
    // Prevent overflow
    if (nonce >= 0xFFFFFFFF) {  // 4.2 billion
        nonce = 0;
    }
}

void sendStats() {
    unsigned long elapsed = millis() - startTime;
    float hashrate = (elapsed > 0) ? (hashCount * 1000.0 / elapsed) : 0;
    
    Serial.print("STATS ");
    Serial.print(hashCount);
    Serial.print(" ");
    Serial.print(hashrate);
    Serial.print(" ");
    Serial.println(millis());
}
