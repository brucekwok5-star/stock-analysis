<?php
// Simple API to receive and store stock signals
// Endpoint: https://openclaw-builder-1etcvswk9hsjwga1.hostingersite.com/api.php

header('Content-Type: application/json');

// Allow cross-origin for n8n
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    exit(0);
}

// Simple secret key check
$secret = $_SERVER['HTTP_X_SECRET'] ?? '';
if ($secret !== 'YOUR_SECRET_KEY_HERE') {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthorized']);
    exit;
}

$method = $_SERVER['REQUEST_METHOD'];

// GET - Return latest signals
if ($method === 'GET') {
    $file = 'signals.json';
    if (file_exists($file)) {
        echo file_get_contents($file);
    } else {
        echo json_encode(['signals' => [], 'updated' => null]);
    }
    exit;
}

// POST - Save new signal
if ($method === 'POST') {
    $input = json_decode(file_get_contents('php://input'), true);

    if (!$input) {
        http_response_code(400);
        echo json_encode(['error' => 'Invalid JSON']);
        exit;
    }

    // Load existing signals
    $file = 'signals.json';
    $data = file_exists($file) ? json_decode(file_get_contents($file), true) : ['signals' => []];

    // Add new signal
    $signal = [
        'id' => uniqid(),
        'timestamp' => date('Y-m-d H:i:s'),
        'data' => $input
    ];

    array_unshift($data['signals'], $signal);

    // Keep only last 50 signals
    $data['signals'] = array_slice($data['signals'], 0, 50);
    $data['updated'] = date('Y-m-d H:i:s');

    file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT));

    echo json_encode(['success' => true, 'id' => $signal['id']]);
    exit;
}

http_response_code(405);
echo json_encode(['error' => 'Method not allowed']);
