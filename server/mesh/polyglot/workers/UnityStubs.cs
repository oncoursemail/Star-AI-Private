// Minimal Unity type shells written for this checker (names and return types only, no bodies that matter).
// They only give expressions a Unity type so that a member which does not exist is reported (CS1061/CS0117). Every
// such report is then checked against the official Unity scripting reference index: a member the docs list but these
// shells lack is a gap here and is ignored, never shown. Members that Unity 6 removed or renamed (Rigidbody.velocity)
// are left out on purpose.
#pragma warning disable
using System;
using System.Collections;
using System.Collections.Generic;

namespace UnityEngine
{
    public class Object
    {
        public string name;
        public static void Destroy(Object obj, float t = 0f) { }
        public static void DestroyImmediate(Object obj) { }
        public static void DontDestroyOnLoad(Object target) { }
        public static T Instantiate<T>(T original) where T : Object => default;
        public static T Instantiate<T>(T original, Transform parent) where T : Object => default;
        public static T Instantiate<T>(T original, Vector3 position, Quaternion rotation) where T : Object => default;
        public static T Instantiate<T>(T original, Vector3 position, Quaternion rotation, Transform parent) where T : Object => default;
        public static Object Instantiate(Object original, Vector3 position, Quaternion rotation) => default;
        public static T FindObjectOfType<T>() where T : Object => default;
        public static T FindFirstObjectByType<T>() where T : Object => default;
        public static T FindAnyObjectByType<T>() where T : Object => default;
        public static T[] FindObjectsOfType<T>() where T : Object => default;
        public static T[] FindObjectsByType<T>(FindObjectsSortMode mode) where T : Object => default;
        public int GetInstanceID() => 0;
        public static implicit operator bool(Object o) => o != null;
    }
    public enum FindObjectsSortMode { None, InstanceID }
    public class Component : Object
    {
        public GameObject gameObject;
        public Transform transform;
        public string tag;
        public T GetComponent<T>() => default;
        public Component GetComponent(Type t) => default;
        public T GetComponentInChildren<T>() => default;
        public T GetComponentInParent<T>() => default;
        public T[] GetComponents<T>() => default;
        public T[] GetComponentsInChildren<T>() => default;
        public bool TryGetComponent<T>(out T component) { component = default; return false; }
        public bool CompareTag(string tag) => false;
        public void SendMessage(string methodName, object value = null) { }
    }
    public class Behaviour : Component { public bool enabled; public bool isActiveAndEnabled; }
    public class MonoBehaviour : Behaviour
    {
        public Coroutine StartCoroutine(IEnumerator routine) => default;
        public void StopCoroutine(Coroutine routine) { }
        public void StopCoroutine(IEnumerator routine) { }
        public void StopAllCoroutines() { }
        public void Invoke(string methodName, float time) { }
        public void InvokeRepeating(string methodName, float time, float repeatRate) { }
        public void CancelInvoke() { }
        public void CancelInvoke(string methodName) { }
        public bool IsInvoking(string methodName) => false;
        public static void print(object message) { }
    }
    public class ScriptableObject : Object { public static T CreateInstance<T>() where T : ScriptableObject => default; }
    public sealed class GameObject : Object
    {
        public GameObject() { }
        public GameObject(string name) { }
        public GameObject(string name, params Type[] components) { }
        public Transform transform;
        public bool activeSelf, activeInHierarchy;
        public string tag;
        public int layer;
        public GameObject gameObject;
        public void SetActive(bool value) { }
        public T GetComponent<T>() => default;
        public T GetComponentInChildren<T>() => default;
        public T GetComponentInParent<T>() => default;
        public T[] GetComponents<T>() => default;
        public T[] GetComponentsInChildren<T>() => default;
        public bool TryGetComponent<T>(out T component) { component = default; return false; }
        public T AddComponent<T>() where T : Component => default;
        public bool CompareTag(string tag) => false;
        public void SendMessage(string methodName, object value = null) { }
        public static GameObject Find(string name) => default;
        public static GameObject FindWithTag(string tag) => default;
        public static GameObject FindGameObjectWithTag(string tag) => default;
        public static GameObject[] FindGameObjectsWithTag(string tag) => default;
        public static GameObject CreatePrimitive(PrimitiveType type) => default;
    }
    public enum PrimitiveType { Sphere, Capsule, Cylinder, Cube, Plane, Quad }
    public class Transform : Component, IEnumerable
    {
        public Vector3 position, localPosition, eulerAngles, localEulerAngles, localScale, lossyScale, forward, right, up;
        public Quaternion rotation, localRotation;
        public Transform parent, root;
        public int childCount;
        public void Translate(Vector3 translation) { }
        public void Translate(Vector3 translation, Space relativeTo) { }
        public void Translate(float x, float y, float z) { }
        public void Rotate(Vector3 eulers) { }
        public void Rotate(Vector3 eulers, Space relativeTo) { }
        public void Rotate(float x, float y, float z) { }
        public void Rotate(Vector3 axis, float angle) { }
        public void RotateAround(Vector3 point, Vector3 axis, float angle) { }
        public void LookAt(Transform target) { }
        public void LookAt(Vector3 worldPosition) { }
        public void LookAt(Vector3 worldPosition, Vector3 worldUp) { }
        public void SetParent(Transform p) { }
        public void SetParent(Transform p, bool worldPositionStays) { }
        public void SetPositionAndRotation(Vector3 position, Quaternion rotation) { }
        public Transform GetChild(int index) => default;
        public Transform Find(string n) => default;
        public Vector3 TransformPoint(Vector3 p) => default;
        public Vector3 InverseTransformPoint(Vector3 p) => default;
        public Vector3 TransformDirection(Vector3 d) => default;
        public Vector3 InverseTransformDirection(Vector3 d) => default;
        public void DetachChildren() { }
        public IEnumerator GetEnumerator() => null;
    }
    public class RectTransform : Transform { public Vector2 anchoredPosition, sizeDelta, anchorMin, anchorMax, pivot; }
    public enum Space { World, Self }
    public struct Vector3
    {
        public float x, y, z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
        public Vector3(float x, float y) { this.x = x; this.y = y; z = 0; }
        public float magnitude, sqrMagnitude;
        public Vector3 normalized => default;
        public static Vector3 zero, one, up, down, left, right, forward, back, positiveInfinity, negativeInfinity;
        public void Normalize() { }
        public void Set(float x, float y, float z) { }
        public float this[int i] { get => 0; set { } }
        public static float Distance(Vector3 a, Vector3 b) => 0;
        public static float Dot(Vector3 a, Vector3 b) => 0;
        public static Vector3 Cross(Vector3 a, Vector3 b) => default;
        public static Vector3 Lerp(Vector3 a, Vector3 b, float t) => default;
        public static Vector3 LerpUnclamped(Vector3 a, Vector3 b, float t) => default;
        public static Vector3 Slerp(Vector3 a, Vector3 b, float t) => default;
        public static Vector3 MoveTowards(Vector3 c, Vector3 t, float d) => default;
        public static Vector3 SmoothDamp(Vector3 c, Vector3 t, ref Vector3 v, float s) => default;
        public static Vector3 SmoothDamp(Vector3 c, Vector3 t, ref Vector3 v, float s, float m) => default;
        public static Vector3 ClampMagnitude(Vector3 v, float m) => default;
        public static Vector3 Normalize(Vector3 v) => default;
        public static Vector3 Project(Vector3 v, Vector3 n) => default;
        public static Vector3 ProjectOnPlane(Vector3 v, Vector3 n) => default;
        public static Vector3 Reflect(Vector3 v, Vector3 n) => default;
        public static Vector3 Scale(Vector3 a, Vector3 b) => default;
        public static Vector3 Min(Vector3 a, Vector3 b) => default;
        public static Vector3 Max(Vector3 a, Vector3 b) => default;
        public static float Angle(Vector3 a, Vector3 b) => 0;
        public static float SignedAngle(Vector3 a, Vector3 b, Vector3 axis) => 0;
        public static Vector3 operator +(Vector3 a, Vector3 b) => default;
        public static Vector3 operator -(Vector3 a, Vector3 b) => default;
        public static Vector3 operator -(Vector3 a) => default;
        public static Vector3 operator *(Vector3 a, float d) => default;
        public static Vector3 operator *(float d, Vector3 a) => default;
        public static Vector3 operator /(Vector3 a, float d) => default;
        public static bool operator ==(Vector3 a, Vector3 b) => true;
        public static bool operator !=(Vector3 a, Vector3 b) => false;
        public static implicit operator Vector2(Vector3 v) => default;
        public static implicit operator Vector3(Vector2 v) => default;
        public override bool Equals(object o) => false;
        public override int GetHashCode() => 0;
    }
    public struct Vector2
    {
        public float x, y;
        public Vector2(float x, float y) { this.x = x; this.y = y; }
        public float magnitude, sqrMagnitude;
        public Vector2 normalized => default;
        public static Vector2 zero, one, up, down, left, right;
        public void Normalize() { }
        public void Set(float x, float y) { }
        public static float Distance(Vector2 a, Vector2 b) => 0;
        public static float Dot(Vector2 a, Vector2 b) => 0;
        public static float Angle(Vector2 a, Vector2 b) => 0;
        public static float SignedAngle(Vector2 a, Vector2 b) => 0;
        public static Vector2 Lerp(Vector2 a, Vector2 b, float t) => default;
        public static Vector2 MoveTowards(Vector2 c, Vector2 t, float d) => default;
        public static Vector2 ClampMagnitude(Vector2 v, float m) => default;
        public static Vector2 Perpendicular(Vector2 v) => default;
        public static Vector2 Reflect(Vector2 v, Vector2 n) => default;
        public static Vector2 SmoothDamp(Vector2 c, Vector2 t, ref Vector2 v, float s) => default;
        public static Vector2 operator +(Vector2 a, Vector2 b) => default;
        public static Vector2 operator -(Vector2 a, Vector2 b) => default;
        public static Vector2 operator -(Vector2 a) => default;
        public static Vector2 operator *(Vector2 a, float d) => default;
        public static Vector2 operator *(float d, Vector2 a) => default;
        public static Vector2 operator /(Vector2 a, float d) => default;
        public static bool operator ==(Vector2 a, Vector2 b) => true;
        public static bool operator !=(Vector2 a, Vector2 b) => false;
        public override bool Equals(object o) => false;
        public override int GetHashCode() => 0;
    }
    public struct Vector2Int { public int x, y; public Vector2Int(int x, int y) { this.x = x; this.y = y; } public static Vector2Int zero, one, up, down, left, right; }
    public struct Vector3Int { public int x, y, z; public Vector3Int(int x, int y, int z) { this.x = x; this.y = y; this.z = z; } public static Vector3Int zero, one; }
    public struct Quaternion
    {
        public float x, y, z, w;
        public Quaternion(float x, float y, float z, float w) { this.x = x; this.y = y; this.z = z; this.w = w; }
        public static Quaternion identity;
        public Vector3 eulerAngles;
        public Quaternion normalized => default;
        public static Quaternion Euler(float x, float y, float z) => default;
        public static Quaternion Euler(Vector3 e) => default;
        public static Quaternion LookRotation(Vector3 forward) => default;
        public static Quaternion LookRotation(Vector3 forward, Vector3 up) => default;
        public static Quaternion Slerp(Quaternion a, Quaternion b, float t) => default;
        public static Quaternion Lerp(Quaternion a, Quaternion b, float t) => default;
        public static Quaternion RotateTowards(Quaternion a, Quaternion b, float d) => default;
        public static Quaternion AngleAxis(float angle, Vector3 axis) => default;
        public static Quaternion FromToRotation(Vector3 a, Vector3 b) => default;
        public static Quaternion Inverse(Quaternion r) => default;
        public static float Angle(Quaternion a, Quaternion b) => 0;
        public static Quaternion operator *(Quaternion a, Quaternion b) => default;
        public static Vector3 operator *(Quaternion r, Vector3 p) => default;
    }
    public struct Color
    {
        public float r, g, b, a;
        public Color(float r, float g, float b) { this.r = r; this.g = g; this.b = b; a = 1; }
        public Color(float r, float g, float b, float a) { this.r = r; this.g = g; this.b = b; this.a = a; }
        public static Color red, green, blue, white, black, yellow, cyan, magenta, gray, grey, clear;
        public static Color Lerp(Color a, Color b, float t) => default;
        public static Color operator *(Color a, float b) => default;
    }
    public struct Color32 { public byte r, g, b, a; public Color32(byte r, byte g, byte b, byte a) { this.r = r; this.g = g; this.b = b; this.a = a; } }
    public struct Rect { public float x, y, width, height; public Rect(float x, float y, float w, float h) { this.x = x; this.y = y; width = w; height = h; } }
    public struct Bounds { public Vector3 center, size, extents, min, max; public bool Contains(Vector3 p) => false; }
    public struct Ray { public Vector3 origin, direction; public Ray(Vector3 o, Vector3 d) { origin = o; direction = d; } public Vector3 GetPoint(float d) => default; }
    public struct LayerMask { public int value; public static int GetMask(params string[] n) => 0; public static int NameToLayer(string n) => 0; public static string LayerToName(int l) => ""; public static implicit operator int(LayerMask m) => 0; public static implicit operator LayerMask(int i) => default; }
    public static class Mathf
    {
        public const float PI = 3.14159274f, Infinity = float.PositiveInfinity, NegativeInfinity = float.NegativeInfinity, Deg2Rad = 0.0174532924f, Rad2Deg = 57.29578f, Epsilon = 1.401298E-45f;
        public static float Abs(float f) => 0; public static int Abs(int v) => 0;
        public static float Clamp(float v, float a, float b) => 0; public static int Clamp(int v, int a, int b) => 0;
        public static float Clamp01(float v) => 0;
        public static float Lerp(float a, float b, float t) => 0; public static float LerpUnclamped(float a, float b, float t) => 0;
        public static float InverseLerp(float a, float b, float v) => 0; public static float LerpAngle(float a, float b, float t) => 0;
        public static float MoveTowards(float c, float t, float d) => 0; public static float MoveTowardsAngle(float c, float t, float d) => 0;
        public static float SmoothDamp(float c, float t, ref float v, float s) => 0; public static float SmoothStep(float a, float b, float t) => 0;
        public static float Sin(float f) => 0; public static float Cos(float f) => 0; public static float Tan(float f) => 0;
        public static float Asin(float f) => 0; public static float Acos(float f) => 0; public static float Atan(float f) => 0; public static float Atan2(float y, float x) => 0;
        public static float Sqrt(float f) => 0; public static float Pow(float f, float p) => 0; public static float Exp(float p) => 0; public static float Log(float f) => 0; public static float Log10(float f) => 0;
        public static float Min(float a, float b) => 0; public static int Min(int a, int b) => 0; public static float Min(params float[] v) => 0;
        public static float Max(float a, float b) => 0; public static int Max(int a, int b) => 0; public static float Max(params float[] v) => 0;
        public static float Floor(float f) => 0; public static int FloorToInt(float f) => 0; public static float Ceil(float f) => 0; public static int CeilToInt(float f) => 0;
        public static float Round(float f) => 0; public static int RoundToInt(float f) => 0; public static float Sign(float f) => 0;
        public static float Repeat(float t, float l) => 0; public static float PingPong(float t, float l) => 0; public static float DeltaAngle(float a, float b) => 0;
        public static bool Approximately(float a, float b) => false; public static float PerlinNoise(float x, float y) => 0;
    }
    public static class Time { public static float deltaTime, time, fixedDeltaTime, timeScale, unscaledDeltaTime, unscaledTime, timeSinceLevelLoad, realtimeSinceStartup, smoothDeltaTime, fixedTime; public static int frameCount; }
    public static class Random
    {
        public static float Range(float a, float b) => 0; public static int Range(int a, int b) => 0;
        public static float value; public static Vector3 insideUnitSphere, onUnitSphere; public static Vector2 insideUnitCircle; public static Quaternion rotation;
        public static void InitState(int seed) { }
    }
    public static class Input
    {
        public static float GetAxis(string n) => 0; public static float GetAxisRaw(string n) => 0;
        public static bool GetKey(KeyCode k) => false; public static bool GetKeyDown(KeyCode k) => false; public static bool GetKeyUp(KeyCode k) => false;
        public static bool GetKey(string k) => false; public static bool GetKeyDown(string k) => false; public static bool GetKeyUp(string k) => false;
        public static bool GetButton(string n) => false; public static bool GetButtonDown(string n) => false; public static bool GetButtonUp(string n) => false;
        public static bool GetMouseButton(int b) => false; public static bool GetMouseButtonDown(int b) => false; public static bool GetMouseButtonUp(int b) => false;
        public static Vector3 mousePosition, acceleration; public static Vector2 mouseScrollDelta; public static bool anyKey, anyKeyDown; public static int touchCount;
        public static Touch GetTouch(int i) => default;
    }
    public struct Touch { public Vector2 position, deltaPosition; public TouchPhase phase; public int fingerId; }
    public enum TouchPhase { Began, Moved, Stationary, Ended, Canceled }
    public enum KeyCode
    {
        None, Backspace, Tab, Return, Escape, Space, Delete, UpArrow, DownArrow, RightArrow, LeftArrow, LeftShift, RightShift, LeftControl, RightControl, LeftAlt, RightAlt,
        A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z,
        Alpha0, Alpha1, Alpha2, Alpha3, Alpha4, Alpha5, Alpha6, Alpha7, Alpha8, Alpha9, F1, F2, F3, F4, F5, Mouse0, Mouse1, Mouse2, KeypadEnter
    }
    public static class Debug
    {
        public static void Log(object m) { } public static void Log(object m, Object c) { } public static void LogFormat(string f, params object[] a) { }
        public static void LogWarning(object m) { } public static void LogWarning(object m, Object c) { }
        public static void LogError(object m) { } public static void LogError(object m, Object c) { } public static void LogException(Exception e) { }
        public static void DrawRay(Vector3 s, Vector3 d) { } public static void DrawRay(Vector3 s, Vector3 d, Color c, float t = 0) { }
        public static void DrawLine(Vector3 s, Vector3 e) { } public static void DrawLine(Vector3 s, Vector3 e, Color c, float t = 0) { }
        public static void Assert(bool c) { } public static void Break() { }
    }
    public static class Gizmos { public static Color color; public static void DrawWireSphere(Vector3 c, float r) { } public static void DrawSphere(Vector3 c, float r) { } public static void DrawWireCube(Vector3 c, Vector3 s) { } public static void DrawCube(Vector3 c, Vector3 s) { } public static void DrawLine(Vector3 a, Vector3 b) { } public static void DrawRay(Vector3 a, Vector3 d) { } }
    public enum ForceMode { Force, Acceleration, Impulse, VelocityChange }
    public enum ForceMode2D { Force, Impulse }
    public enum RigidbodyType2D { Dynamic, Kinematic, Static }
    public enum RigidbodyInterpolation { None, Interpolate, Extrapolate }
    public enum CollisionDetectionMode { Discrete, Continuous, ContinuousDynamic, ContinuousSpeculative }
    [Flags] public enum RigidbodyConstraints { None = 0, FreezePositionX = 2, FreezePositionY = 4, FreezePositionZ = 8, FreezeRotationX = 16, FreezeRotationY = 32, FreezeRotationZ = 64, FreezePosition = 14, FreezeRotation = 112, FreezeAll = 126 }
    public class Rigidbody : Component
    {
        public Vector3 linearVelocity, angularVelocity, position, centerOfMass;
        public Quaternion rotation;
        public float mass, linearDamping, angularDamping, maxAngularVelocity;
        public bool useGravity, isKinematic, detectCollisions;
        public RigidbodyConstraints constraints; public RigidbodyInterpolation interpolation; public CollisionDetectionMode collisionDetectionMode;
        public void AddForce(Vector3 f) { } public void AddForce(Vector3 f, ForceMode m) { } public void AddForce(float x, float y, float z) { }
        public void AddRelativeForce(Vector3 f, ForceMode m = ForceMode.Force) { } public void AddTorque(Vector3 t, ForceMode m = ForceMode.Force) { }
        public void AddRelativeTorque(Vector3 t, ForceMode m = ForceMode.Force) { } public void AddForceAtPosition(Vector3 f, Vector3 p, ForceMode m = ForceMode.Force) { }
        public void AddExplosionForce(float f, Vector3 p, float r, float u = 0, ForceMode m = ForceMode.Force) { }
        public void MovePosition(Vector3 p) { } public void MoveRotation(Quaternion r) { } public void Sleep() { } public void WakeUp() { }
    }
    public class Rigidbody2D : Component
    {
        public Vector2 linearVelocity, position; public float angularVelocity, rotation, mass, gravityScale, linearDamping, angularDamping;
        public bool isKinematic, simulated, freezeRotation; public RigidbodyType2D bodyType; public RigidbodyConstraints2D constraints;
        public void AddForce(Vector2 f) { } public void AddForce(Vector2 f, ForceMode2D m) { } public void AddTorque(float t, ForceMode2D m = ForceMode2D.Force) { }
        public void AddRelativeForce(Vector2 f, ForceMode2D m = ForceMode2D.Force) { } public void MovePosition(Vector2 p) { } public void MoveRotation(float a) { }
    }
    [Flags] public enum RigidbodyConstraints2D { None = 0, FreezePositionX = 1, FreezePositionY = 2, FreezeRotation = 4, FreezePosition = 3, FreezeAll = 7 }
    public class Collider : Component { public bool enabled, isTrigger; public Bounds bounds; public Rigidbody attachedRigidbody; public Vector3 ClosestPoint(Vector3 p) => default; }
    public class BoxCollider : Collider { public Vector3 center, size; }
    public class SphereCollider : Collider { public Vector3 center; public float radius; }
    public class CapsuleCollider : Collider { public Vector3 center; public float radius, height; }
    public class MeshCollider : Collider { public bool convex; }
    public class CharacterController : Collider
    {
        public bool isGrounded; public Vector3 velocity, center; public float height, radius, slopeLimit, stepOffset, skinWidth;
        public CollisionFlags Move(Vector3 motion) => default; public bool SimpleMove(Vector3 speed) => false;
    }
    [Flags] public enum CollisionFlags { None = 0, Sides = 1, Above = 2, Below = 4 }
    public class Collider2D : Component { public bool enabled, isTrigger; public Bounds bounds; public Rigidbody2D attachedRigidbody; }
    public class BoxCollider2D : Collider2D { public Vector2 size, offset; }
    public class CircleCollider2D : Collider2D { public float radius; public Vector2 offset; }
    public class CapsuleCollider2D : Collider2D { public Vector2 size, offset; }
    public struct ContactPoint { public Vector3 point, normal; public Collider thisCollider, otherCollider; public float separation; }
    public struct ContactPoint2D { public Vector2 point, normal; public Collider2D collider, otherCollider; }
    public class Collision
    {
        public GameObject gameObject; public Collider collider; public Transform transform; public Rigidbody rigidbody;
        public Vector3 relativeVelocity, impulse; public ContactPoint[] contacts; public int contactCount;
        public ContactPoint GetContact(int i) => default;
    }
    public class Collision2D
    {
        public GameObject gameObject; public Collider2D collider, otherCollider; public Transform transform; public Rigidbody2D rigidbody;
        public Vector2 relativeVelocity; public ContactPoint2D[] contacts; public int contactCount; public ContactPoint2D GetContact(int i) => default;
    }
    public struct RaycastHit { public Vector3 point, normal; public float distance; public Collider collider; public Transform transform; public Rigidbody rigidbody; }
    public struct RaycastHit2D { public Vector2 point, normal; public float distance, fraction; public Collider2D collider; public Transform transform; public Rigidbody2D rigidbody; public static implicit operator bool(RaycastHit2D h) => false; }
    public enum QueryTriggerInteraction { UseGlobal, Ignore, Collide }
    public static class Physics
    {
        public static Vector3 gravity;
        public static bool Raycast(Vector3 o, Vector3 d) => false;
        public static bool Raycast(Vector3 o, Vector3 d, float max) => false;
        public static bool Raycast(Vector3 o, Vector3 d, float max, int mask) => false;
        public static bool Raycast(Vector3 o, Vector3 d, out RaycastHit hit) { hit = default; return false; }
        public static bool Raycast(Vector3 o, Vector3 d, out RaycastHit hit, float max) { hit = default; return false; }
        public static bool Raycast(Vector3 o, Vector3 d, out RaycastHit hit, float max, int mask) { hit = default; return false; }
        public static bool Raycast(Vector3 o, Vector3 d, out RaycastHit hit, float max, int mask, QueryTriggerInteraction q) { hit = default; return false; }
        public static bool Raycast(Ray r) => false;
        public static bool Raycast(Ray r, float max) => false;
        public static bool Raycast(Ray r, out RaycastHit hit) { hit = default; return false; }
        public static bool Raycast(Ray r, out RaycastHit hit, float max) { hit = default; return false; }
        public static bool Raycast(Ray r, out RaycastHit hit, float max, int mask) { hit = default; return false; }
        public static RaycastHit[] RaycastAll(Ray r, float max = float.PositiveInfinity, int mask = -1) => default;
        public static RaycastHit[] RaycastAll(Vector3 o, Vector3 d, float max = float.PositiveInfinity, int mask = -1) => default;
        public static bool SphereCast(Vector3 o, float r, Vector3 d, out RaycastHit hit, float max = float.PositiveInfinity, int mask = -1) { hit = default; return false; }
        public static Collider[] OverlapSphere(Vector3 p, float r) => default;
        public static Collider[] OverlapSphere(Vector3 p, float r, int mask) => default;
        public static Collider[] OverlapBox(Vector3 c, Vector3 h) => default;
        public static Collider[] OverlapBox(Vector3 c, Vector3 h, Quaternion o, int mask = -1) => default;
        public static int OverlapSphereNonAlloc(Vector3 p, float r, Collider[] results, int mask = -1) => 0;
        public static bool CheckSphere(Vector3 p, float r, int mask = -1) => false;
        public static bool Linecast(Vector3 a, Vector3 b) => false;
        public static bool Linecast(Vector3 a, Vector3 b, out RaycastHit hit) { hit = default; return false; }
        public static void IgnoreCollision(Collider a, Collider b, bool ignore = true) { }
        public static void IgnoreLayerCollision(int a, int b, bool ignore = true) { }
    }
    public static class Physics2D
    {
        public static Vector2 gravity;
        public static RaycastHit2D Raycast(Vector2 o, Vector2 d) => default;
        public static RaycastHit2D Raycast(Vector2 o, Vector2 d, float max) => default;
        public static RaycastHit2D Raycast(Vector2 o, Vector2 d, float max, int mask) => default;
        public static Collider2D OverlapCircle(Vector2 p, float r) => default;
        public static Collider2D OverlapCircle(Vector2 p, float r, int mask) => default;
        public static Collider2D[] OverlapCircleAll(Vector2 p, float r, int mask = -1) => default;
        public static Collider2D OverlapBox(Vector2 p, Vector2 s, float a, int mask = -1) => default;
        public static RaycastHit2D BoxCast(Vector2 o, Vector2 s, float a, Vector2 d, float max = float.PositiveInfinity, int mask = -1) => default;
        public static RaycastHit2D CircleCast(Vector2 o, float r, Vector2 d, float max = float.PositiveInfinity, int mask = -1) => default;
        public static RaycastHit2D Linecast(Vector2 a, Vector2 b, int mask = -1) => default;
        public static void IgnoreCollision(Collider2D a, Collider2D b, bool ignore = true) { }
    }
    public class Camera : Behaviour
    {
        public static Camera main;
        public float fieldOfView, orthographicSize, nearClipPlane, farClipPlane, aspect; public bool orthographic; public Color backgroundColor;
        public Vector3 ScreenToWorldPoint(Vector3 p) => default; public Vector3 WorldToScreenPoint(Vector3 p) => default;
        public Vector3 ViewportToWorldPoint(Vector3 p) => default; public Vector3 WorldToViewportPoint(Vector3 p) => default;
        public Ray ScreenPointToRay(Vector3 p) => default; public Ray ViewportPointToRay(Vector3 p) => default;
    }
    public class AudioClip : Object { public float length; }
    public class AudioSource : Behaviour
    {
        public AudioClip clip; public float volume, pitch, time, spatialBlend; public bool isPlaying, loop, mute, playOnAwake;
        public void Play() { } public void Play(ulong delay) { } public void PlayDelayed(float d) { } public void PlayOneShot(AudioClip c) { } public void PlayOneShot(AudioClip c, float v) { }
        public void Stop() { } public void Pause() { } public void UnPause() { }
        public static void PlayClipAtPoint(AudioClip c, Vector3 p) { } public static void PlayClipAtPoint(AudioClip c, Vector3 p, float v) { }
    }
    public class RuntimeAnimatorController : Object { }
    public class Animator : Behaviour
    {
        public float speed; public bool applyRootMotion; public RuntimeAnimatorController runtimeAnimatorController;
        public void SetTrigger(string n) { } public void SetTrigger(int id) { } public void ResetTrigger(string n) { }
        public void SetBool(string n, bool v) { } public void SetBool(int id, bool v) { } public bool GetBool(string n) => false;
        public void SetFloat(string n, float v) { } public void SetFloat(int id, float v) { } public void SetFloat(string n, float v, float d, float t) { } public float GetFloat(string n) => 0;
        public void SetInteger(string n, int v) { } public void SetInteger(int id, int v) { } public int GetInteger(string n) => 0;
        public void Play(string s) { } public void Play(string s, int layer, float t = 0) { } public void CrossFade(string s, float d) { }
        public static int StringToHash(string n) => 0;
        public AnimatorStateInfo GetCurrentAnimatorStateInfo(int layer) => default;
    }
    public struct AnimatorStateInfo { public float normalizedTime, length; public bool IsName(string n) => false; }
    public class Renderer : Component { public bool enabled; public Material material, sharedMaterial; public Material[] materials; public Bounds bounds; }
    public class MeshRenderer : Renderer { }
    public class SkinnedMeshRenderer : Renderer { }
    public class LineRenderer : Renderer { public int positionCount; public float startWidth, endWidth; public Color startColor, endColor; public void SetPosition(int i, Vector3 p) { } public void SetPositions(Vector3[] p) { } }
    public class TrailRenderer : Renderer { public float time; public void Clear() { } }
    public class Sprite : Object { public Rect rect; public Bounds bounds; }
    public class SpriteRenderer : Renderer { public Sprite sprite; public Color color; public bool flipX, flipY; public int sortingOrder; public string sortingLayerName; }
    public class Texture : Object { public int width, height; }
    public class Texture2D : Texture { public Texture2D(int w, int h) { } public void SetPixel(int x, int y, Color c) { } public Color GetPixel(int x, int y) => default; public void Apply() { } }
    public class Shader : Object { public static Shader Find(string n) => default; public static int PropertyToID(string n) => 0; }
    public class Material : Object
    {
        public Material(Shader s) { } public Material(Material m) { }
        public Color color; public Texture mainTexture; public Shader shader;
        public void SetColor(string n, Color c) { } public void SetFloat(string n, float v) { } public void SetInt(string n, int v) { } public void SetTexture(string n, Texture t) { }
        public Color GetColor(string n) => default; public float GetFloat(string n) => 0; public void EnableKeyword(string k) { } public void DisableKeyword(string k) { }
    }
    public class Mesh : Object { public Vector3[] vertices, normals; public int[] triangles; public Vector2[] uv; public void RecalculateNormals() { } public void RecalculateBounds() { } public void Clear() { } }
    public class MeshFilter : Component { public Mesh mesh, sharedMesh; }
    public class Light : Behaviour { public Color color; public float intensity, range; }
    public class ParticleSystem : Component { public bool isPlaying; public void Play() { } public void Stop() { } public void Emit(int c) { } public void Clear() { } }
    public class Canvas : Behaviour { }
    public static class Application
    {
        public static void Quit() { } public static int targetFrameRate; public static bool isPlaying, isEditor, isFocused; public static string persistentDataPath, dataPath, version, productName;
        public static RuntimePlatform platform; public static void OpenURL(string u) { }
    }
    public enum RuntimePlatform { WindowsPlayer, OSXPlayer, LinuxPlayer, Android, IPhonePlayer, WebGLPlayer, WindowsEditor, OSXEditor, LinuxEditor }
    public static class Screen { public static int width, height; public static bool fullScreen; public static float dpi; }
    public static class Cursor { public static CursorLockMode lockState; public static bool visible; }
    public enum CursorLockMode { None, Locked, Confined }
    public static class PlayerPrefs
    {
        public static void SetInt(string k, int v) { } public static int GetInt(string k) => 0; public static int GetInt(string k, int d) => 0;
        public static void SetFloat(string k, float v) { } public static float GetFloat(string k) => 0; public static float GetFloat(string k, float d) => 0;
        public static void SetString(string k, string v) { } public static string GetString(string k) => ""; public static string GetString(string k, string d) => "";
        public static bool HasKey(string k) => false; public static void DeleteKey(string k) { } public static void DeleteAll() { } public static void Save() { }
    }
    public static class JsonUtility { public static string ToJson(object o) => ""; public static string ToJson(object o, bool p) => ""; public static T FromJson<T>(string j) => default; public static void FromJsonOverwrite(string j, object o) { } }
    public static class Resources { public static T Load<T>(string p) where T : Object => default; public static Object Load(string p) => default; public static T[] LoadAll<T>(string p) where T : Object => default; }
    public class Coroutine : YieldInstruction { }
    public class YieldInstruction { }
    public class CustomYieldInstruction : IEnumerator { public virtual bool keepWaiting => false; public object Current => null; public bool MoveNext() => false; public void Reset() { } }
    public sealed class WaitForSeconds : YieldInstruction { public WaitForSeconds(float s) { } }
    public sealed class WaitForSecondsRealtime : CustomYieldInstruction { public WaitForSecondsRealtime(float s) { } }
    public sealed class WaitForEndOfFrame : YieldInstruction { }
    public sealed class WaitForFixedUpdate : YieldInstruction { }
    public sealed class WaitUntil : CustomYieldInstruction { public WaitUntil(Func<bool> p) { } }
    public sealed class WaitWhile : CustomYieldInstruction { public WaitWhile(Func<bool> p) { } }
    public class PropertyAttribute : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public sealed class SerializeField : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public sealed class SerializeReference : Attribute { }
    [AttributeUsage(AttributeTargets.Field)] public sealed class HideInInspector : Attribute { }
    public sealed class HeaderAttribute : PropertyAttribute { public HeaderAttribute(string h) { } }
    public sealed class TooltipAttribute : PropertyAttribute { public TooltipAttribute(string t) { } }
    public sealed class RangeAttribute : PropertyAttribute { public RangeAttribute(float a, float b) { } }
    public sealed class MinAttribute : PropertyAttribute { public MinAttribute(float m) { } }
    public sealed class SpaceAttribute : PropertyAttribute { public SpaceAttribute() { } public SpaceAttribute(float h) { } }
    public sealed class TextAreaAttribute : PropertyAttribute { public TextAreaAttribute() { } public TextAreaAttribute(int a, int b) { } }
    [AttributeUsage(AttributeTargets.Class, AllowMultiple = true)] public sealed class RequireComponent : Attribute { public RequireComponent(Type t) { } public RequireComponent(Type a, Type b) { } }
    [AttributeUsage(AttributeTargets.Class)] public sealed class DisallowMultipleComponent : Attribute { }
    [AttributeUsage(AttributeTargets.Class)] public sealed class ExecuteInEditMode : Attribute { }
    [AttributeUsage(AttributeTargets.Class)] public sealed class ExecuteAlways : Attribute { }
    [AttributeUsage(AttributeTargets.Class)] public sealed class AddComponentMenu : Attribute { public AddComponentMenu(string m) { } }
    [AttributeUsage(AttributeTargets.Class)] public sealed class CreateAssetMenuAttribute : Attribute { public string fileName, menuName; public int order; }
    [AttributeUsage(AttributeTargets.Method)] public sealed class ContextMenu : Attribute { public ContextMenu(string n) { } }
    [AttributeUsage(AttributeTargets.Method)] public sealed class RuntimeInitializeOnLoadMethodAttribute : Attribute { public RuntimeInitializeOnLoadMethodAttribute() { } public RuntimeInitializeOnLoadMethodAttribute(RuntimeInitializeLoadType t) { } }
    public enum RuntimeInitializeLoadType { AfterSceneLoad, BeforeSceneLoad }
    namespace Events
    {
        public delegate void UnityAction(); public delegate void UnityAction<T0>(T0 a);
        public class UnityEventBase { public void RemoveAllListeners() { } }
        public class UnityEvent : UnityEventBase { public void AddListener(UnityAction c) { } public void RemoveListener(UnityAction c) { } public void Invoke() { } }
        public class UnityEvent<T0> : UnityEventBase { public void AddListener(UnityAction<T0> c) { } public void RemoveListener(UnityAction<T0> c) { } public void Invoke(T0 a) { } }
    }
    namespace SceneManagement
    {
        public struct Scene { public string name, path; public int buildIndex; public bool isLoaded; }
        public enum LoadSceneMode { Single, Additive }
        public static class SceneManager
        {
            public static void LoadScene(string n) { } public static void LoadScene(int i) { } public static void LoadScene(string n, LoadSceneMode m) { } public static void LoadScene(int i, LoadSceneMode m) { }
            public static AsyncOperation LoadSceneAsync(string n) => default; public static AsyncOperation LoadSceneAsync(int i) => default; public static AsyncOperation LoadSceneAsync(string n, LoadSceneMode m) => default;
            public static Scene GetActiveScene() => default; public static int sceneCountInBuildSettings; public static int sceneCount;
            public static event Events.UnityAction<Scene, LoadSceneMode> sceneLoaded;
        }
    }
    namespace Events { public delegate void UnityAction<T0, T1>(T0 a, T1 b); }
    public class AsyncOperation : YieldInstruction { public bool isDone, allowSceneActivation; public float progress; }
    namespace AI
    {
        public class NavMeshAgent : Behaviour
        {
            public Vector3 destination, velocity, desiredVelocity; public float speed, angularSpeed, acceleration, stoppingDistance, remainingDistance, radius, height;
            public bool isStopped, hasPath, pathPending, updateRotation, updatePosition, isOnNavMesh; public bool SetDestination(Vector3 t) => false; public void ResetPath() { } public bool Warp(Vector3 p) => false;
        }
        public struct NavMeshHit { public Vector3 position; public float distance; public bool hit; }
        public static class NavMesh { public static bool SamplePosition(Vector3 s, out NavMeshHit h, float d, int a) { h = default; return false; } public const int AllAreas = -1; }
    }
    namespace UI
    {
        public class Graphic : Behaviour { public Color color; public RectTransform rectTransform; }
        public class MaskableGraphic : Graphic { }
        public class Text : MaskableGraphic { public string text; public int fontSize; }
        public class Image : MaskableGraphic { public Sprite sprite; public float fillAmount; public bool preserveAspect; public Image.Type type; public enum Type { Simple, Sliced, Tiled, Filled } }
        public class RawImage : MaskableGraphic { public Texture texture; }
        public class Selectable : Behaviour { public bool interactable; }
        public class Button : Selectable { public ButtonClickedEvent onClick; public class ButtonClickedEvent : Events.UnityEvent { } }
        public class Toggle : Selectable { public bool isOn; public Events.UnityEvent<bool> onValueChanged; }
        public class Slider : Selectable { public float value, minValue, maxValue; public bool wholeNumbers; public Events.UnityEvent<float> onValueChanged; }
        public class InputField : Selectable { public string text; public Events.UnityEvent<string> onValueChanged, onEndEdit; }
        public class Dropdown : Selectable { public int value; }
        public class ScrollRect : Behaviour { public Vector2 normalizedPosition; public float verticalNormalizedPosition; }
        public class LayoutRebuilder { public static void ForceRebuildLayoutImmediate(RectTransform r) { } }
    }
}

namespace TMPro
{
    public class TMP_Text : UnityEngine.UI.MaskableGraphic { public string text; public float fontSize; public void SetText(string t) { } public void SetText(string t, float a) { } }
    public class TextMeshProUGUI : TMP_Text { }
    public class TextMeshPro : TMP_Text { }
    public class TMP_InputField : UnityEngine.UI.Selectable { public string text; public UnityEngine.Events.UnityEvent<string> onValueChanged, onEndEdit, onSubmit; }
    public class TMP_Dropdown : UnityEngine.UI.Selectable { public int value; }
}
