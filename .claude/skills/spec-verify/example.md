## The following is an example of a bad implementation

**File purpose**: A product requirement that explains what needs to be done.
**File path:** docs/prd/im-0-hello-world.md
**File content:**

```text
IM-0 - Hello World

## Goal

The user see a `Hello world` message at the console.
```

**File purpose**: A spec file that explains how it needs to be done.
**File path:** specs/im-0-hello-world.md
**File content:**

```
console.log("Hello world");
```

**File purpose**: A spec file that explains how it needs to be done.
**File path:** src/main.js
**File content:**

```javascript
console.log('Hello');
```

**Conclusion:** The implementation was bad since the implemented code did not achieve the correct goal required on the prd file and neither did not follow the correct approach from the spec file.

## The following is an example of a good implementation

**File purpose**: A product requirement that explains what needs to be done.
**File path:** docs/prd/im-0-hello-world.md
**File content:**

```text
IM-0 - Hello World

## Goal

The user see a `Hello world` message at the console.
```

**File purpose**: A spec file that explains how it needs to be done.
**File path:** specs/im-0-hello-world.md
**File content:**

```
console.log("Hello world");
```

**File purpose**: A spec file that explains how it needs to be done.
**File path:** src/main.js
**File content:**

```javascript
console.log('Hello world');
```

**Conclusion:** The implementation was good because the implemented code did achieve the correct goal required on the prd file and followed the correct approach from the spec file.
